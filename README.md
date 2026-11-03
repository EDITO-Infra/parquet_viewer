# Minimal Parquet URL Viewer

This project includes a tiny web UI:
- Paste a parquet URL
- Click **Render**
- See the first rows in a table

## Start the application

From the project root, run:

```powershell
python main.py
```

`main.py` installs the locked frontend dependencies when needed, builds the React
frontend, starts the API, and serves the built UI from the same process at
`http://127.0.0.1:8000`. Press `Ctrl+C` to stop it. Node.js/npm must be installed
on the machine; Python dependencies still come from `requirements.txt`.

## API endpoint

- `POST /view`
- Body:

```json
{
  "parquet_url": "https://.../file.parquet",
  "max_rows": 50,
  "columns": ["datasetid", "eventdate"]
}
```

The endpoint returns `columns` and `data` from `ParquetViewService.get_view`.

- `POST /schema`
- Body:

```json
{
  "parquet_url": "https://.../file.parquet"
}
```

Returns available parquet columns (`name`, `dtype`) for the column picker.

## Build, run, and publish with Docker

Use one image name for the local and Docker Hub image:

```text
{docker_user_name}/{docker_image_name}:{version}
```

Replace the placeholders in the commands below. For example:

```text
docker_user_name = willemboone
docker_image_name = bioflow_data
version = v1.0.0
```

Log in to Docker Hub:

```powershell
docker login
```

Build the image:

```powershell
docker build -t {docker_user_name}/{docker_image_name}:{version} .
```

Run the image locally:

```powershell
docker run --rm -p 8000:8000 {docker_user_name}/{docker_image_name}:{version}
```

Open <http://localhost:8000>.

Push the same image to Docker Hub:

```powershell
docker push {docker_user_name}/{docker_image_name}:{version}
```

The Docker Hub repository
`{docker_user_name}/{docker_image_name}` must exist before pushing. The
container listens on port `8000`, and the `-p 8000:8000` option maps it to the
same port on the host.
