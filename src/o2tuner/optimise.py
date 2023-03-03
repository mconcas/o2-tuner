"""
Optimise hook, wrapping parallelisation
"""

from time import sleep
from math import floor
from multiprocessing import Process
from multiprocessing import set_start_method as mp_set_start_method
import functools

from o2tuner.io import make_dir, parse_yaml
from o2tuner.backends import OptunaHandler, can_do_storage
from o2tuner.sampler import construct_sampler
from o2tuner.inspector import O2TunerInspector
from o2tuner.log import Log

# Do this to run via fork by default on latest iOS
mp_set_start_method("fork")

LOG = Log()


def optimise_run(objective, optuna_storage_config, sampler_config, n_trials, work_dir, user_config, in_memory):
    """
    Run one of those per job
    """
    handler = OptunaHandler(optuna_storage_config.get("name", None), optuna_storage_config.get("storage", None), work_dir, user_config, in_memory)
    handler.set_objective(objective)
    handler.set_sampler(construct_sampler(sampler_config))
    handler.initialise(n_trials)
    handler.optimise()
    handler.finalise()
    return 0


def optimise(objective, optuna_config, *, work_dir="o2tuner_optimise", user_config=None):
    """
    This is the entry point function for all optimisation runs

    args and kwargs will be forwarded to the objective function
    """

    # read in the configurations, if string, assume to parse a YAML, otherwise it is assumed to be a dictionary
    if isinstance(optuna_config, str):
        optuna_config = parse_yaml(optuna_config)

    trials = optuna_config.get("trials", 100)
    jobs = optuna_config.get("jobs", 1)

    # investigate storage properties
    optuna_storage_config = optuna_config.get("study", {})

    in_memory = False
    if not optuna_storage_config.get("name", None) or not optuna_storage_config.get("storage", None):
        # we reduce the number of jobs to 1. Either missing the table name or the storage path will anyway always lead to a new study
        LOG.info("No storage provided, running only one job.")
        in_memory = True
        jobs = 1

    if "storage" in optuna_storage_config and not can_do_storage(optuna_storage_config["storage"]):
        return False

    if trials < jobs:
        LOG.info(f"Attempt to do {trials} trials, hence reducing the number of jobs from {jobs} to {trials}")
        jobs = trials

    trials_list = floor(trials / jobs)
    trials_list = [trials_list] * jobs
    # add the left-over trials as equally as possible
    for i in range(trials - sum(trials_list)):
        trials_list[i] += 1

    LOG.info(f"Number of jobs: {jobs}\nNumber of trials: {trials}")

    make_dir(work_dir)

    procs = []
    for trial in trials_list:
        procs.append(Process(target=optimise_run,
                             args=(objective, optuna_storage_config, optuna_config.get("sampler", None), trial, work_dir, user_config, in_memory)))
        procs[-1].start()
        sleep(5)

    while True:
        is_alive = any(p.is_alive() for p in procs)
        if not is_alive:
            break
        # We assume here that the optimisation might take some time, so we can sleep for a bit
        sleep(10)

    insp = O2TunerInspector()
    insp.load(optuna_config, work_dir)
    insp.write_summary()
    return True


def needs_cwd(func):
    """
    Decorator to be used for objective functions to indicate whether they need a dedicated directory to run in
    """
    @functools.wraps(func)
    def decorator(*args, **kwargs):
        return func(*args, **kwargs)
    decorator.needs_cwd = True
    return decorator
