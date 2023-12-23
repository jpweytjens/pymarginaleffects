import polars as pl
import re
import numpy as np
import polars as pl
import warnings
import patsy
from abc import ABC, abstractmethod


class ModelAbstract(ABC):
    def __init__(self, model):
        self.model = model
        self.validate_coef()
        self.validate_modeldata()
        self.validate_response_name()
        self.validate_formula()

    def validate_coef(self):
        coef = self.get_coef()
        if not isinstance(coef, np.ndarray):
            raise ValueError("coef must be a numpy array")
        self.coef = coef

    def validate_modeldata(self):
        modeldata = self.get_modeldata()
        if not isinstance(modeldata, pl.DataFrame):
            raise ValueError("modeldata must be a Polars DataFrame")
        self.modeldata = modeldata

    def validate_response_name(self):
        response_name = self.get_response_name()
        if not isinstance(response_name, str):
            raise ValueError("response_name must be a string")
        self.response_name = response_name

    def validate_formula(self):
        formula = self.get_formula()
        if not isinstance(formula, str):
            raise ValueError("formula must be a string")
        self.formula = formula

    @abstractmethod
    def get_vcov_raw(self):
        pass

    def get_vcov(self, vcov=True):
        vcov = self.get_vcov_raw(vcov)
        if not isinstance(vcov, np.ndarray):
            raise ValueError("vcov must be a numpy array")
        if vcov.shape != (len(self.coef), len(self.coef)):
            raise ValueError(
                "vcov must be a square numpy array with dimensions equal to the length of self.coef"
            )
        return vcov

    @abstractmethod
    def get_modeldata(self):
        pass

    @abstractmethod
    def get_response_name(self):
        pass

    @abstractmethod
    def get_variables_names(self):
        pass

    @abstractmethod
    def get_predict(self):
        pass

    @abstractmethod
    def get_formula(self):
        pass


class ModelStatsmodels(ModelAbstract):
    def get_coef(self):
        return np.array(self.model.params)

    def get_modeldata(self):
        df = self.model.model.data.frame
        if not isinstance(df, pl.DataFrame):
            df = pl.from_pandas(df)
        return df

    def get_response_name(self):
        return self.model.model.endog_names

    def get_vcov_raw(self, vcov=True):
        if isinstance(vcov, bool):
            if vcov is True:
                V = self.model.cov_params()
            else:
                V = None
        elif isinstance(vcov, str):
            lab = f"cov_{vcov}"
            if hasattr(self.model, lab):
                V = getattr(self.model, lab)
            else:
                raise ValueError(f"The model object has no {lab} attribute.")
        else:
            raise ValueError(
                '`vcov` must be a boolean or a string like "HC3", which corresponds to an attribute of the model object such as "vcov_HC3".'
            )
        V = np.array(V)
        return V

    def get_variables_names(self, variables, newdata):
        if variables is None:
            variables = self.model.model.exog_names
            variables = [re.sub("\[.*\]", "", x) for x in variables]
            variables = [x for x in variables if x in newdata.columns]
            variables = pl.Series(variables).unique().to_list()
        if isinstance(variables, (str, dict)):
            variables = [variables] if isinstance(variables, str) else variables
        elif isinstance(variables, list) and all(
            isinstance(var, str) for var in variables
        ):
            pass
        else:
            raise ValueError(
                "`variables` must be None, a dict, string, or list of strings"
            )
        good = [x for x in variables if x in newdata.columns]
        bad = [x for x in variables if x not in newdata.columns]
        if len(bad) > 0:
            bad = ", ".join(bad)
            warnings.warn(f"Variable(s) not in newdata: {bad}")
        if len(good) == 0:
            raise ValueError("There is no valid column name in `variables`.")
        return variables

    def get_predict(self, params, newdata: pl.DataFrame):
        if isinstance(newdata, np.ndarray):
            exog = newdata
        else:
            y, exog = patsy.dmatrices(self.model.model.formula, newdata.to_pandas())
        p = self.model.model.predict(params, exog)
        if p.ndim == 1:
            p = pl.DataFrame({"rowid": range(newdata.shape[0]), "estimate": p})
        elif p.ndim == 2:
            colnames = {f"column_{i}": str(i) for i in range(p.shape[1])}
            p = (
                pl.DataFrame(p)
                .rename(colnames)
                .with_columns(
                    pl.Series(range(p.shape[0]), dtype=pl.Int32).alias("rowid")
                )
                .melt(id_vars="rowid", variable_name="group", value_name="estimate")
            )
        else:
            raise ValueError(
                "The `predict()` method must return an array with 1 or 2 dimensions."
            )
        p = p.with_columns(pl.col("rowid").cast(pl.Int32))
        return p

    def get_formula(self):
        return self.model.model.formula
