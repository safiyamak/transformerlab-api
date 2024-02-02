# Root dir is the parent of the parent of this current directory:

import os
from pathlib import Path
import transformerlab.db as db


# TFL_HOME_DIR
if "TFL_HOME_DIR" in os.environ:
    HOME_DIR = os.environ["TFL_HOME_DIR"]
    if not os.path.exists(HOME_DIR):
        print(f"Error: Home directory {HOME_DIR} does not exist")
        exit(1)
    print(f"Home directory is set to: {HOME_DIR}")
else:
    HOME_DIR = Path.home() / ".transformerlab"
    os.makedirs(name=HOME_DIR, exist_ok=True)
    print(f"Using default home directory: {HOME_DIR}")

# TFL_WORKSPACE_DIR
if "TFL_WORKSPACE_DIR" in os.environ:
    WORKSPACE_DIR = os.environ["TFL_WORKSPACE_DIR"]
    if not os.path.exists(WORKSPACE_DIR):
        print(f"Error: Workspace directory {WORKSPACE_DIR} does not exist")
        exit(1)
    print(f"Workspace is set to: {WORKSPACE_DIR}")
else:
    WORKSPACE_DIR = os.path.join(HOME_DIR, "workspace")
    os.makedirs(name=WORKSPACE_DIR, exist_ok=True)
    print(f"Using default workspace directory: {WORKSPACE_DIR}")

# TFL_SOURCE_CODE_DIR
api_py_dir = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if (api_py_dir != os.path.join(HOME_DIR, "src")):
    print(
        f"We are working from {api_py_dir} which is not {os.path.join(HOME_DIR, 'src')}")
    print("That means you are probably developing in a different location so we will set source dir to the current directory")
    TFL_SOURCE_CODE_DIR = api_py_dir
else:
    print(f"Source code directory is set to: {os.path.join(HOME_DIR, 'src')}")
    TFL_SOURCE_CODE_DIR = os.path.join(HOME_DIR, "src")

# EXPERIMENTS_DIR
EXPERIMENTS_DIR: str = os.path.join(WORKSPACE_DIR, "experiments")
print(f"Experiments directory is set to: {EXPERIMENTS_DIR}")
os.makedirs(name=EXPERIMENTS_DIR, exist_ok=True)

# GLOBAL_LOG_PATH
GLOBAL_LOG_PATH = os.path.join(HOME_DIR, "transformerlab.log")

# ROOT_DIR (deprecate later)
ROOT_DIR = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))


def experiment_dir_by_name(experiment_name: str) -> str:
    return os.path.join(EXPERIMENTS_DIR, experiment_name)


async def experiment_dir_by_id(experiment_id: str) -> str:
    if (experiment_id is not None):
        experiment = await db.experiment_get(experiment_id)
    else:
        print("Error: experiment_id is None")
        return os.path.join(EXPERIMENTS_DIR, "error")

    experiment_name = experiment['name']
    return os.path.join(EXPERIMENTS_DIR, experiment_name)

# PLUGIN_PRELOADED_GALLERY
PLUGIN_PRELOADED_GALLERY = os.path.join(
    TFL_SOURCE_CODE_DIR, "transformerlab", "plugins")

# PLUGIN_DIR
PLUGIN_DIR = os.path.join(WORKSPACE_DIR, "plugins")


def plugin_dir_by_name(plugin_name: str) -> str:
    return os.path.join(PLUGIN_DIR, plugin_name)


TEMP_DIR = os.path.join(WORKSPACE_DIR, "temp")
os.makedirs(name=TEMP_DIR, exist_ok=True)
