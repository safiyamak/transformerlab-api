import os
import re
import shutil
import unicodedata
import json
import aiofiles
from datasets import load_dataset, load_dataset_builder
from fastapi import APIRouter, HTTPException, UploadFile, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Union, Any

import transformerlab.db as db
from transformerlab.shared import dirs
from datasets.data_files import EmptyDatasetError
from transformerlab.shared.shared import slugify

from jinja2 import Environment
jinja_environment = Environment()

router = APIRouter(prefix="/data", tags=["datasets"])

# Get list of datasets that we have in our hardcoded gallery


class SuccessResponse(BaseModel):
    status: str
    data: Dict[str, Any]


class ErrorResponse(BaseModel):
    status: str
    message: str


@router.get("/gallery", summary="Display the datasets available in the dataset gallery.", responses={200: {"model": SuccessResponse, "description": "Successful response. Data is a list of column names followed by data, which can be of any datatype."},
                                                                                                     400: {"model": ErrorResponse},
                                                                                                     })
async def dataset_gallery() -> Any:

    file_location = os.path.join(
        dirs.TFL_SOURCE_CODE_DIR, "transformerlab", "galleries", "data-gallery.json")
    with open(file_location) as f:
        gallery = json.load(f)
    local_datasets = await db.get_datasets()

    local_dataset_names = set(str(dataset['dataset_id'])
                              for dataset in local_datasets)
    for dataset in gallery:
        dataset['downloaded'] = True if dataset['huggingfacerepo'] in local_dataset_names else False
    return {"status": "success", "data": gallery}

# Get info on dataset from huggingface


@router.get("/info", summary="Fetch the details of a particular dataset.")
async def dataset_info(dataset_id: str):
    d = await db.get_dataset(dataset_id)
    if d is None:
        return {}
    r = {}
    # This means it is a custom dataset the user uploaded
    if d["location"] == "local":
        try:
            dataset = load_dataset(path=dirs.dataset_dir_by_id(dataset_id))
        except EmptyDatasetError:
            return {"status": "error", "message": "The dataset is empty."}
        split = list(dataset.keys())[0]
        r["features"] = dataset[split].features
    else:
        dataset_config = d.get("json_data", {}).get("dataset_config", None)
        if (dataset_config is not None):
            ds_builder = load_dataset_builder(
                dataset_id, dataset_config, trust_remote_code=True)
        else:
            ds_builder = load_dataset_builder(
                dataset_id, trust_remote_code=True)
        r = {
            "description": ds_builder.info.description,
            "features": ds_builder.info.features,
            "dataset_size": ds_builder.info.dataset_size,
            "download_size": ds_builder.info.download_size,
            "citation": ds_builder.info.citation,
            "homepage": ds_builder.info.homepage,
            "license": ds_builder.info.license,
            "splits": ds_builder.info.splits,
            "supervised_keys": ds_builder.info.supervised_keys,
            "version": ds_builder.info.version,
        }
    return r


@router.get("/preview", summary="Preview the contents of a dataset.", responses={200: {"model": SuccessResponse, "description": "Successful response. Data is a list of column names followed by data, which can be of any datatype."},
                                                                                 400: {"model": ErrorResponse},
                                                                                 }
            )
async def dataset_preview(dataset_id: str = Query(description="The ID of the dataset to preview. This can be a HuggingFace dataset ID or a local dataset ID."),
                          offset: int = Query(
                              0, description='The starting index from where to fetch the data.', ge=0),
                          split: str = Query(
                              None, description='The split to preview. This can be train, test, or validation.'),
                          limit: int = Query(
                              10, description="The maximum number of data items to fetch.", ge=1, le=1000),
                          streaming: bool = False) -> Any:
    d = await db.get_dataset(dataset_id)
    dataset_len = 0
    result = {}

    try:
        if d["location"] == "local":
            dataset = load_dataset(path=dirs.dataset_dir_by_id(
                dataset_id), streaming=streaming)
        else:
            dataset_config = d.get("json_data", {}).get("dataset_config", None)
            if dataset_config is not None:
                dataset = load_dataset(
                    dataset_id, dataset_config, trust_remote_code=True, streaming=streaming)
            else:
                dataset = load_dataset(
                    dataset_id, trust_remote_code=True, streaming=streaming)
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        return {"status": "error", "message": error_msg}

    if (split is None or split == ""):
        splits = list(dataset.keys())
        if len(splits) == 0:
            return {"status": "error", "message": "No splits available in the dataset."}
        split = splits[0]

    if streaming:
        dataset_len = -1
        dataset = dataset[split].skip(offset)
        result['rows'] = list(dataset.take(limit))
        result['splits'] = None
    else:
        if d["location"] != "local" and split not in dataset.keys():
            return {"status": "error", "message": f"Split '{split}' does not exist in the dataset."}
        dataset_len = len(dataset[split])
        result['columns'] = dataset[split][offset:min(
            offset + limit, dataset_len)]
        result['splits'] = list(dataset.keys())

    result['len'] = dataset_len
    return {"status": "success", "data": result}


@router.get("/preview_with_template", summary="Preview the contents of a dataset after applying a jinja template to it.", responses={200: {"model": SuccessResponse, "description": "Successful response. Data is a list of column names followed by data, which can be of any datatype."},
                                                                                                                                     400: {"model": ErrorResponse},
                                                                                                                                     }
            )
async def dataset_preview_with_template(dataset_id: str = Query(description="The ID of the dataset to preview. This can be a HuggingFace dataset ID or a local dataset ID."),
                                        template: str = '',
                                        offset: int = Query(
        0, description='The starting index from where to fetch the data.', ge=0),
        limit: int = Query(10, description="The maximum number of data items to fetch.", ge=1, le=1000)) -> Any:
    d = await db.get_dataset(dataset_id)
    dataset_len = 0
    result = {}
    # This means it is a custom dataset the user uploaded
    if d["location"] == "local":
        try:
            dataset = load_dataset(path=dirs.dataset_dir_by_id(dataset_id))
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            return {"status": "error", "message":  error_msg}
        dataset_len = len(dataset["train"])
        result['columns'] = dataset["train"][offset:min(
            offset+limit, dataset_len)]
    else:
        dataset_config = d.get("json_data", {}).get("dataset_config", None)
        if (dataset_config is not None):
            dataset = load_dataset(
                dataset_id, dataset_config, trust_remote_code=True)
        else:
            dataset = load_dataset(dataset_id, trust_remote_code=True)
        dataset_len = len(dataset["train"])
        result['columns'] = dataset["train"][offset:min(
            offset+limit, dataset_len)]
    result['len'] = dataset_len

    jinja_template = jinja_environment.from_string(template)

    column_names = list(result['columns'].keys())

    rows = []
    # now iterate over all columns and rows, do not use offset or len because we've already
    # sliced the dataset
    for i in range(0, len(result['columns'][column_names[0]])):
        row = {}
        row['__index__'] = i + offset
        for key in result['columns'].keys():
            row[key] = result['columns'][key][i]

        # Apply the template to a new key in row called __formatted__
        row['__formatted__'] = jinja_template.render(row)
        # row['__template__'] = template
        rows.append(row)

    return {"status": "success", "data": {"columns": column_names, "rows": rows, "len": dataset_len, "offset": offset, "limit": limit}}


@router.get("/download", summary="Download a dataset from the HuggingFace Hub to the LLMLab server.")
async def dataset_download(dataset_id: str):
    # Check to make sure we don't have a dataset with this name
    # Possibly we want to allow redownloading in the future but for we can't add duplicate dataset_id to the DB
    row = await db.get_dataset(dataset_id)
    if row is not None:
        return {"status": "error", "message": f"A dataset with the name {dataset_id} already exists"}

    # Try to get the dataset info from the gallery
    gallery = []
    json_data = {}
    file_location = os.path.join(
        dirs.TFL_SOURCE_CODE_DIR, "transformerlab", "galleries", "data-gallery.json")
    with open(file_location) as f:
        gallery = json.load(f)
    for dataset in gallery:
        if dataset["huggingfacerepo"] == dataset_id:
            json_data = dataset

    try:
        dataset_config = json_data.get("dataset_config", None)
        if (dataset_config is not None):
            ds_builder = load_dataset_builder(
                dataset_id, dataset_config, trust_remote_code=True)
        else:
            ds_builder = load_dataset_builder(
                dataset_id, trust_remote_code=True)
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        return {"status": "error", "message": error_msg}

    dataset_size = ds_builder.info.download_size
    if not dataset_size:
        dataset_size = -1
    await db.create_huggingface_dataset(
        dataset_id, ds_builder.info.description, dataset_size, json_data
    )

    # Download the dataset
    # Later on we can move this to a job
    try:
        dataset = load_dataset(dataset_id, trust_remote_code=True)
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        return {"status": "error", "message": error_msg}

    return {"status": "success"}


@router.get("/list", summary="List available datasets.")
async def dataset_list():
    list = await db.get_datasets()
    return list  # convert list to JSON object


@router.get("/new", summary="Create a new dataset.")
async def dataset_new(dataset_id: str):
    dataset_id = slugify(dataset_id)

    # Check to make sure we don't have a dataset with this name
    row = await db.get_dataset(dataset_id)
    if row is not None:
        return {"status": "error", "message": f"A dataset with the name {dataset_id} already exists"}

    # Create a new dataset in the database
    await db.create_local_dataset(dataset_id)

    # Now make a directory that maps to the above dataset_id
    # Check if the directory already exists
    if not os.path.exists(dirs.dataset_dir_by_id(dataset_id)):
        os.makedirs(dirs.dataset_dir_by_id(dataset_id))
    return {"status": "success", "dataset_id": dataset_id}


@router.get("/delete", summary="Delete a dataset.")
async def dataset_delete(dataset_id: str):
    await db.delete_dataset(dataset_id)

    # delete directory and contents. ignore_errors because we don't care if the directory doesn't exist
    shutil.rmtree(dirs.dataset_dir_by_id(dataset_id), ignore_errors=True)

    return {"status": "success"}


@router.post("/fileupload", summary="Upload the contents of a dataset.")
async def create_upload_file(dataset_id: str, files: list[UploadFile]):
    for file in files:
        print("uploading filename is: " + str(file.filename))

        # # ensure filename is in the format <something>_train.jsonl or <something>_eval.jsonl
        # if not re.match(r"^.+_(train|eval).jsonl$", str(file.filename)):
        #     raise HTTPException(
        #         status_code=403, detail=f"The filenames must be named EXACTLY: {dataset_id}_train.jsonl and {dataset_id}_eval.jsonl")

        # ensure the filename is exactly {dataset_id}_train.jsonl or {dataset_id}_eval.jsonl

        # if not re.match(rf"^{dataset_id}_(train|eval).jsonl$", str(file.filename)):
        #     raise HTTPException(
        #         status_code=403, detail=f"The filenames must be named EXACTLY: {dataset_id}_train.jsonl and {dataset_id}_eval.jsonl")

        dataset_id = slugify(dataset_id)

        # Save the file to the dataset directory
        try:
            content = await file.read()
            newfilename = os.path.join(
                dirs.dataset_dir_by_id(dataset_id), str(file.filename))
            async with aiofiles.open(newfilename, "wb") as out_file:
                await out_file.write(content)
        except Exception:
            raise HTTPException(
                status_code=403, detail="There was a problem uploading the file")

    return {"status": "success"}
