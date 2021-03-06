from itertools import tee
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, Optional, Tuple, Union, cast
from warnings import warn

from jsonschema import Draft7Validator  # type: ignore

from rcds import errors

from ..util import load_any

if TYPE_CHECKING:  # pragma: no cover
    from rcds import Project


config_schema_validator = Draft7Validator(
    schema=load_any(Path(__file__).parent / "challenge.schema.yaml")
)


class TargetNotFoundError(errors.ValidationError):
    pass


class TargetFileNotFoundError(TargetNotFoundError):
    target: Path

    def __init__(self, message: str, target: Path):
        super().__init__(message)
        self.target = target


class ConfigLoader:
    """
    Object that manages loading challenge config files
    """

    project: "Project"

    def __init__(self, project: "Project"):
        """
        :param rcds.Project project: project context to use
        """
        self.project = project

    def parse_config(
        self, config_file: Path
    ) -> Iterable[Union[errors.ValidationError, Dict[str, Any]]]:
        """
        Load and validate a config file, returning both the config and any
        errors encountered.

        :param pathlib.Path config_file: The challenge config to load
        :returns: Iterable containing any errors (all instances of
            :class:`rcds.errors.ValidationError`) and the parsed config. The config will
            always be last.
        """
        root = config_file.parent
        config = load_any(config_file)

        config.setdefault("id", root.name)  # derive id from parent directory name

        schema_errors: Iterable[errors.SchemaValidationError] = (
            errors.SchemaValidationError(str(e), e)
            for e in config_schema_validator.iter_errors(config)
        )
        # Make a duplicate to check whethere there are errors returned
        schema_errors, schema_errors_dup = tee(schema_errors)
        # This is the same test as used in Validator.is_valid
        if next(schema_errors_dup, None) is not None:
            yield from schema_errors
        else:
            if "expose" in config:
                if "containers" not in config:
                    yield TargetNotFoundError(
                        "Cannot expose ports without containers defined"
                    )
                else:
                    for key, expose_objs in config["expose"].items():
                        if key not in config["containers"]:
                            yield TargetNotFoundError(
                                f'`expose` references container "{key}" but '
                                f"it is not defined in `containers`"
                            )
                        else:
                            for expose_obj in expose_objs:
                                if (
                                    expose_obj["target"]
                                    not in config["containers"][key]["ports"]
                                ):
                                    yield TargetNotFoundError(
                                        f"`expose` references port "
                                        f'{expose_obj["target"]} on container '
                                        f'"{key}" which is not defined'
                                    )
            if "provide" in config:
                for f in config["provide"]:
                    f = Path(f)
                    if not (root / f).is_file():
                        yield TargetFileNotFoundError(
                            f'`provide` references file "{str(f)}" which does not '
                            f"exist",
                            f,
                        )
            if "flag" in config:
                if isinstance(config["flag"], dict):
                    if "file" in config["flag"]:
                        f = Path(config["flag"]["file"])
                        f_resolved = root / f
                        if f_resolved.is_file():
                            with f_resolved.open("r") as fd:
                                flag = fd.read().strip()
                            config["flag"] = flag
                        else:
                            yield TargetFileNotFoundError(
                                f'`flag.file` references file "{str(f)}" which does '
                                f"not exist",
                                f,
                            )
                if isinstance(config["flag"], str) and config["flag"].count("\n") > 0:
                    warn(
                        RuntimeWarning(
                            "Flag contains multiple lines; is this intended?"
                        )
                    )
        yield config

    def check_config(
        self, config_file: Path
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Iterable[errors.ValidationError]]]:
        """
        Load and validate a config file, returning any errors encountered.

        If the config file is valid, the tuple returned contains the loaded config as
        the first element, and the second element is None. Otherwise, the second
        element is an iterable of errors that occurred during validation

        This method wraps :meth:`parse_config`.

        :param pathlib.Path config_file: The challenge config to load
        """
        load_data = self.parse_config(config_file)
        load_data, load_data_dup = tee(load_data)
        first = next(load_data_dup)
        if isinstance(first, errors.ValidationError):
            validation_errors = cast(
                Iterable[errors.ValidationError],
                filter(lambda v: isinstance(v, errors.ValidationError), load_data),
            )
            return (None, validation_errors)
        else:
            return (first, None)

    def load_config(self, config_file: Path) -> Dict[str, Any]:
        """
        Loads a config file, or throw an exception if it is not valid

        This method wraps :meth:`check_config`, and throws the first error returned
        if there are any errors.

        :param pathlib.Path config_file: The challenge config to load
        :returns: The loaded config
        """
        config, errors = self.check_config(config_file)
        if errors is not None:
            raise next(iter(errors))
        # errors is None
        assert config is not None
        return config
