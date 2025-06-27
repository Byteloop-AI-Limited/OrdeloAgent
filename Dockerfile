# Use the official AWS Lambda Python 3.12 base image
FROM public.ecr.aws/lambda/python:3.12

# Install system dependencies
# RUN microdnf install -y postgresql-libs postgresql-devel gcc


# Set working directory and Python pathq
ENV PYTHONPATH="${PYTHONPATH}:/var/task"
WORKDIR /var/task

# Copy application code and requirements
COPY config ./config
COPY ordelo ./ordelo
COPY utils_common ./utils_common
COPY watomation ./watomation
COPY requirements.txt .

# Install dependencies using uv with system flag
# With pip
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# With uv
# RUN pip install uv
# RUN uv pip install --system -r requirements.txt

# Set the CMD to your handler
CMD ["watomation.fapp_ordelo_agent.lambda_handler"]