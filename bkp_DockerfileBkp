FROM tiangolo/uvicorn-gunicorn-fastapi:python3.11

# Update default packages
RUN apt-get update

RUN apt-get install -y \
    build-essential \
    curl

# Update new packages
RUN apt-get update

## Get Rust
#RUN curl https://sh.rustup.rs -sSf | bash -s -- -y
## Set Path
#ENV PATH="/root/.cargo/bin:${PATH}"

# Install UV package manager
RUN pip install uv
COPY requirements.txt /tmp/requirements.txt
RUN uv install /tmp/requirements.txt

COPY ./start.sh /start.sh
RUN chmod +x /start.sh

# Copy project files
# COPY ./app /app/
COPY . .