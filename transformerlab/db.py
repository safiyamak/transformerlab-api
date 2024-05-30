import itertools
import json
import os
import sqlite3

import aiosqlite
from transformerlab.shared import dirs

db = None

DATABASE_FILE_NAME = f"{dirs.WORKSPACE_DIR}/llmlab.sqlite3"


async def init():
    """
    Create the database, tables, and workspace folder if they don't exist.
    """
    global db
    os.makedirs(os.path.dirname(DATABASE_FILE_NAME), exist_ok=True)

    db = await aiosqlite.connect(DATABASE_FILE_NAME)

    await db.execute(
        "CREATE TABLE IF NOT EXISTS model(id INTEGER PRIMARY KEY, model_id UNIQUE, name, json_data JSON)"
    )
    await db.execute(
        "CREATE TABLE IF NOT EXISTS dataset(id INTEGER PRIMARY KEY, dataset_id UNIQUE, location, description, size, config_name)"
    )
    await db.execute(
        """CREATE TABLE IF NOT EXISTS 
                     training_template
                     (id INTEGER PRIMARY KEY, 
                     name UNIQUE, 
                     description, 
                     type, 
                     datasets, 
                     config, 
                     created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, 
                     updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)
                     """
    )
    await db.execute(
        """CREATE TABLE IF NOT EXISTS
                     job
                        (id INTEGER PRIMARY KEY,
                        job_data JSON,
                        status,
                        type,
                        experiment_id,
                        progress INTEGER DEFAULT -1,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT current_timestamp)
                        """
    )

    await db.execute(
        """CREATE TABLE IF NOT EXISTS
                     experiment
                        (id INTEGER PRIMARY KEY,
                        name UNIQUE,
                        config JSON,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT current_timestamp)
                        """
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_name ON experiment (name)"
    )

    await db.execute(
        """CREATE TABLE IF NOT EXISTS
            plugins
                (id INTEGER PRIMARY KEY,
                name UNIQUE,
                type TEXT)"""
    )
    await db.execute(
        """CREATE TABLE IF NOT EXISTS
            config
                (id INTEGER PRIMARY KEY,
                key UNIQUE,
                value TEXT)"""
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_key ON config (key)"
    )

    print("✅ Database initialized")

    print("✅ SEED DATA")
    await db.execute(
        "INSERT OR IGNORE INTO experiment(name, config) VALUES (?, ?)", (
            "alpha", "{}")
    )
    await db.execute(
        "INSERT OR IGNORE INTO experiment(name, config) VALUES (?, ?)", (
            "beta", "{}")
    )
    await db.execute(
        "INSERT OR IGNORE INTO experiment(name, config) VALUES (?, ?)", (
            "gamma", "{}")
    )
    await db.commit()

    # On startup, look for any jobs that are in the IN_PROGRESS state and set them to CANCELLED instead:
    # This is to handle the case where the server is restarted while a job is running.
    await job_cancel_in_progress_jobs()

    return


async def close():

    await db.close()


###############
# DATASETS MODEL
###############


async def get_dataset(dataset_id):

    cursor = await db.execute(
        "SELECT * FROM dataset WHERE dataset_id = ?", (dataset_id,)
    )
    row = await cursor.fetchone()

    # Make sure the dataset exists before formatting repsonse
    if row is None:
        return None

    # convert to json
    desc = cursor.description
    column_names = [col[0] for col in desc]
    row = dict(itertools.zip_longest(column_names, row))

    await cursor.close()
    return row


async def get_datasets():

    cursor = await db.execute("SELECT rowid, * FROM dataset")
    rows = await cursor.fetchall()

    # convert to json:
    desc = cursor.description
    column_names = [col[0] for col in desc]
    data = [dict(itertools.zip_longest(column_names, row)) for row in rows]
    await cursor.close()

    return data


async def create_huggingface_dataset(dataset_id, description, size, config_name=None):
    await db.execute("ALTER TABLE dataset ADD COLUMN config_name TEXT")
    await db.execute(
        """
        INSERT INTO dataset (dataset_id, location, description, size, config_name) 
        VALUES (?, ?, ?, ?, ?)
        """,
        (dataset_id, "huggingfacehub", description, size,
         "" if config_name is None else config_name),
    )
    await db.commit()


async def create_local_dataset(dataset_id):
    await db.execute("ALTER TABLE dataset ADD COLUMN config_name TEXT")
    await db.execute(
        """
        INSERT INTO dataset (dataset_id, location, description, size, config_name) 
        VALUES (?, ?, ?, ?, ?)
        """,
        (dataset_id, "local", "", -1, ""),
    )
    await db.commit()


async def delete_dataset(dataset_id):

    await db.execute("DELETE FROM dataset WHERE dataset_id = ?", (dataset_id,))
    await db.commit()


###############
# MODELS MODEL
###############

async def model_local_list():

    cursor = await db.execute("SELECT rowid, * FROM model")
    rows = await cursor.fetchall()

    # Convert to JSON
    desc = cursor.description
    column_names = [col[0] for col in desc]
    data = [dict(itertools.zip_longest(column_names, row)) for row in rows]
    await cursor.close()

    # convert json_data column from JSON to Python object
    for row in data:
        row["json_data"] = json.loads(row["json_data"])

    return data


async def model_local_create(model_id, name, json_data):

    json_data = json.dumps(obj=json_data)

    await db.execute(
        "INSERT OR REPLACE INTO model(model_id, name, json_data) VALUES (?, ?,?)", (
            model_id, name, json_data)
    )

    await db.commit()


async def model_local_get(model_id):

    cursor = await db.execute("SELECT rowid, * FROM model WHERE model_id = ?", (model_id,))
    row = await cursor.fetchone()

    # Returns None if the model_id isn't in the database
    if row is None:
        return None

    # Map column names to row data
    desc = cursor.description
    column_names = [col[0] for col in desc]
    row = dict(itertools.zip_longest(column_names, row))
    await cursor.close()

    # convert json_data column from JSON to Python object
    row["json_data"] = json.loads(row["json_data"])

    return row


async def model_local_delete(model_id):

    await db.execute("DELETE FROM model WHERE model_id = ?", (model_id,))
    await db.commit()

###############
# GENERIC JOBS MODEL
###############


async def job_create(type, status, job_data='{}', experiment_id=""):

    row = await db.execute_insert(
        "INSERT INTO job(type, status, experiment_id, job_data) VALUES (?, ?, ?, json(?))",
        (type, status, experiment_id, job_data),
    )
    await db.commit()  # is this necessary?
    return row[0]


async def jobs_get_all(type='', status=''):

    base_query = "SELECT * FROM job"
    if type != '':
        base_query += " WHERE type = ?"
    else:
        base_query += " WHERE ? != 'x'"

    if status != '':
        base_query += " AND status = ?"
    else:
        base_query += " AND ? != 'x'"

    cursor = await db.execute(base_query, (type, status))
    rows = await cursor.fetchall()

    # Add column names to output
    desc = cursor.description
    column_names = [col[0] for col in desc]
    data = [dict(itertools.zip_longest(column_names, row)) for row in rows]
    await cursor.close()

    # for each row in data, convert the job_data
    # column from JSON to a Python object
    for i in range(len(data)):
        data[i]["job_data"] = json.loads(data[i]["job_data"])

    return data


async def jobs_get_all_by_experiment_and_type(experiment_id, job_type):

    cursor = await db.execute(
        "SELECT * FROM job \
        WHERE experiment_id = ? \
        AND type = ? \
        ORDER BY created_at DESC", (experiment_id, job_type))
    rows = await cursor.fetchall()

    # Add column names to output
    desc = cursor.description
    column_names = [col[0] for col in desc]
    data = [dict(itertools.zip_longest(column_names, row)) for row in rows]
    await cursor.close()

    # for each row in data, convert the job_data
    # column from JSON to a Python object
    for row in data:
        row["job_data"] = json.loads(row["job_data"])

    return data


async def job_get_status(job_id):

    cursor = await db.execute("SELECT status FROM job WHERE job_id = ?", (job_id,))
    row = await cursor.fetchone()
    await cursor.close()
    return row


async def job_get_error_msg(job_id):

    cursor = await db.execute("SELECT job_data FROM job WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    await cursor.close()
    job_data = json.loads(row[0])
    return job_data.get("error_msg", None)


async def job_get(job_id):

    cursor = await db.execute("SELECT * FROM job WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    # convert to json:
    desc = cursor.description
    column_names = [col[0] for col in desc]
    row = dict(itertools.zip_longest(column_names, row))
    await cursor.close()

    row['job_data'] = json.loads(row['job_data'])
    return row


async def job_count_running():

    cursor = await db.execute("SELECT COUNT(*) FROM job WHERE status = 'RUNNING'")
    row = await cursor.fetchone()
    await cursor.close()
    return row[0]


async def jobs_get_next_queued_job():

    cursor = await db.execute(
        "SELECT * FROM job WHERE status = 'QUEUED' ORDER BY created_at ASC LIMIT 1"
    )
    row = await cursor.fetchone()

    # if no results, return None
    if row is None:
        return None

    # convert to json:
    desc = cursor.description
    column_names = [col[0] for col in desc]
    row = dict(itertools.zip_longest(column_names, row))

    await cursor.close()
    return row


async def job_update_status(job_id, status, error_msg=None):

    await db.execute("UPDATE job SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, job_id))
    await db.commit()
    if error_msg:
        job_data = json.dumps({"error_msg": str(error_msg)})
        await db.execute("UPDATE job SET job_data = ? WHERE id = ?", (job_data, job_id))
        await db.commit()
    return


async def job_update(job_id, type, status):

    await db.execute(
        "UPDATE job SET type = ?, status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (type, status, job_id))
    await db.commit()
    return


def job_update_sync(job_id, status):
    # This is a synchronous version of job_update
    # It is used by popen_and_call function
    # which can only support sychronous functions
    # This is a hack to get around that limitation
    global DATABASE_FILE_NAME
    db_sync = sqlite3.connect(DATABASE_FILE_NAME)

    db_sync.execute(
        "UPDATE job SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, job_id))
    db_sync.commit()
    db_sync.close()
    return


async def job_delete_all():
    await db.execute("DELETE FROM job")
    await db.commit()
    return


async def job_delete(job_id):
    print("Deleting job: " + job_id)
    await db.execute("DELETE FROM job WHERE id = ?", (job_id,))
    await db.commit()
    return


async def job_cancel_in_progress_jobs():
    await db.execute("UPDATE job SET status = 'CANCELLED' WHERE status = 'IN_PROGRESS'")
    await db.commit()
    return

###############
# TRAINING and TRAINING JOBS MODELS
###############


async def get_training_template(id):

    cursor = await db.execute("SELECT * FROM training_template WHERE id = ?", (id,))
    row = await cursor.fetchone()

    # convert to json:
    desc = cursor.description
    column_names = [col[0] for col in desc]
    row = dict(itertools.zip_longest(column_names, row))

    await cursor.close()

    return row


async def get_training_templates():

    cursor = await db.execute("SELECT * FROM training_template")
    rows = await cursor.fetchall()
    await cursor.close()
    return rows


async def create_training_template(name, description, type, datasets, config):

    await db.execute(
        "INSERT INTO training_template(name, description, type, datasets, config) VALUES (?, ?, ?, ?, ?)",
        (name, description, type, datasets, config),
    )
    await db.commit()
    return


async def delete_training_template(id):

    await db.execute("DELETE FROM training_template WHERE id = ?", (id,))
    await db.commit()
    return


# Because this joins on training template it only returns training jobs
async def training_jobs_get_all():

    # Join on the nested JSON value "template_id"
    # #in the job_data column
    cursor = await db.execute(
        "SELECT j.*, tt.id as tt_id, tt.config from job as j \
            JOIN training_template as tt \
            ON  json_extract(j.job_data, '$.template_id') = tt.id \
            "
    )
    rows = await cursor.fetchall()

    # Convert to JSON
    desc = cursor.description
    column_names = [col[0] for col in desc]
    data = [dict(itertools.zip_longest(column_names, row)) for row in rows]
    await cursor.close()

    # for each row in data, convert the job_data
    # and config column from JSON to a Python object
    for row in data:
        row["job_data"] = json.loads(row["job_data"])
        row["config"] = json.loads(row["config"])

    return data


async def training_job_create(template_id, description, experiment_id):

    job_data = {
        "template_id": template_id,
        "description": description,
    }

    job_data = json.dumps(job_data)

    row = await db.execute_insert(
        "INSERT INTO job(type, status, experiment_id, job_data) VALUES (?, ?, ?, json(?))",
        ("TRAIN", "QUEUED", experiment_id, job_data),
    )
    await db.commit()  # is this necessary?
    return row[0]


async def job_get_for_template_id(template_id):

    cursor = await db.execute("SELECT * FROM job WHERE template_id = ?", (template_id,))
    rows = await cursor.fetchall()
    await cursor.close()
    return rows

####################
# EXPEORT JOBS MODEL
# Export jobs use the job_data JSON object to store:
# - exporter_name
# - input_model_id
# - input_model_architecture
# - output_model_id
# - output_model_architecture
# - output_model_name
# - output_model_path
# - params
####################


async def export_job_create(experiment_id, job_data_json):
    job_id = await job_create("EXPORT_MODEL", "Started", job_data_json, experiment_id)
    return job_id


###################
# EXPERIMENTS MODEL
###################

async def experiment_get_all():

    cursor = await db.execute("SELECT * FROM experiment")
    rows = await cursor.fetchall()
    # Do the following to convert the return into a JSON object with keys
    desc = cursor.description
    column_names = [col[0] for col in desc]
    data = [dict(itertools.zip_longest(column_names, row)) for row in rows]
    await cursor.close()
    return data


async def experiment_create(name, config):

    # use python insert and commit command
    row = await db.execute_insert(
        "INSERT INTO experiment(name, config) VALUES (?, ?)", (name, config)
    )
    await db.commit()
    return row[0]


async def experiment_get(id):

    if (id == None or id == "undefined"):
        return None
    cursor = await db.execute("SELECT * FROM experiment WHERE id = ?", (id,))
    row = await cursor.fetchone()

    if row is None:
        return None

    # Convert the SQLite row into a JSON object with keys
    desc = cursor.description
    column_names = [col[0] for col in desc]
    row = dict(itertools.zip_longest(column_names, row))

    await cursor.close()
    return row


async def experiment_get_by_name(name):

    cursor = await db.execute("SELECT * FROM experiment WHERE name = ?", (name,))
    row = await cursor.fetchone()

    if row is None:
        return None

    # Convert the SQLite row into a JSON object with keys
    desc = cursor.description
    column_names = [col[0] for col in desc]
    row = dict(itertools.zip_longest(column_names, row))

    await cursor.close()
    return row


async def experiment_delete(id):

    await db.execute("DELETE FROM experiment WHERE id = ?", (id,))
    await db.commit()
    return


async def experiment_update(id, config):

    await db.execute("UPDATE experiment SET config = ? WHERE id = ?", (config, id))
    await db.commit()
    return


async def experiment_update_config(id, key, value):

    value = json.dumps(value)

    await db.execute(
        f"UPDATE experiment SET config = json_set(config,'$.{key}', json(?))  WHERE id = ?",
        (value, id),
    )
    await db.commit()
    return


async def experiment_save_prompt_template(id, template):

    # The following looks the JSON blob called "config" and adds a key called "prompt_template" if it doesn't exist
    # it then sets the value of that key to the value of the template parameter
    # This is the pattern to follow for updating fields in the config JSON blob
    await db.execute(
        "UPDATE experiment SET config = json_set(config,'$.prompt_template', json(?))  WHERE id = ?",
        (template, id),
    )
    await db.commit()
    return


###############
# PLUGINS MODEL
###############

async def get_plugins():

    cursor = await db.execute("SELECT id, * FROM plugins")
    rows = await cursor.fetchall()
    desc = cursor.description
    column_names = [col[0] for col in desc]
    data = [dict(itertools.zip_longest(column_names, row)) for row in rows]
    await cursor.close()
    return data


async def get_plugins_of_type(type: str):

    cursor = await db.execute("SELECT id, * FROM plugins WHERE type = ?", (type,))
    rows = await cursor.fetchall()
    desc = cursor.description
    column_names = [col[0] for col in desc]
    data = [dict(itertools.zip_longest(column_names, row)) for row in rows]
    await cursor.close()
    return data


async def get_plugin(slug: str):

    cursor = await db.execute("SELECT id, * FROM plugins WHERE name = ?", (slug,))
    row = await cursor.fetchone()
    desc = cursor.description
    column_names = [col[0] for col in desc]
    row = dict(itertools.zip_longest(column_names, row))
    await cursor.close()
    return row


async def save_plugin(name: str, type: str):

    await db.execute("INSERT OR REPLACE INTO plugins (name, type) VALUES (?, ?)", (name, type))
    await db.commit()
    return


###############
# Config MODEL
###############

async def config_get(key: str):

    cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = await cursor.fetchone()
    await cursor.close()
    if row:
        return row[0]
    else:
        return None


async def config_set(key: str, value: str):

    await db.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
    await db.commit()
    return
