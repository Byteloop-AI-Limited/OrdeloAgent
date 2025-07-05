#! /usr/bin/env sh
set -e

# Display the contents of the .env file if it exists
ENV_FILE=${ENV_FILE:-"/app/.env"}  # Change this path according to where your .env is located
if [ -f "$ENV_FILE" ]; then
    echo "Displaying contents of $ENV_FILE:"
    cat "$ENV_FILE"
else
    echo "No .env file found at $ENV_FILE"
fi

# if [ -f /app/app/main.py ]; then
#     DEFAULT_MODULE_NAME=app.main
# elif [ -f /app/main.py ]; then
#     DEFAULT_MODULE_NAME=main
# fi

# Only change for railway deployment
DEFAULT_MODULE_NAME=watomation.fapp_ordelo_agent


MODULE_NAME=${MODULE_NAME:-$DEFAULT_MODULE_NAME}
VARIABLE_NAME=${VARIABLE_NAME:-app}
export APP_MODULE=${APP_MODULE:-"$MODULE_NAME:$VARIABLE_NAME"}

# Print the values of MODULE_NAME, VARIABLE_NAME, and APP_MODULE
echo "MODULE_NAME: $MODULE_NAME"
echo "VARIABLE_NAME: $VARIABLE_NAME"
echo "APP_MODULE: $APP_MODULE"


if [ -f /app/gunicorn_conf.py ]; then
    DEFAULT_GUNICORN_CONF=/app/gunicorn_conf.py
elif [ -f /app/app/gunicorn_conf.py ]; then
    DEFAULT_GUNICORN_CONF=/app/app/gunicorn_conf.py
else
    DEFAULT_GUNICORN_CONF=/gunicorn_conf.py
fi
export GUNICORN_CONF=${GUNICORN_CONF:-$DEFAULT_GUNICORN_CONF}
export WORKER_CLASS=${WORKER_CLASS:-"uvicorn.workers.UvicornWorker"}

# If there's a prestart.sh script in the /app directory or other path specified, run it before starting
PRE_START_PATH=${PRE_START_PATH:-/app/prestart.sh}
echo "Checking for script in $PRE_START_PATH"
if [ -f $PRE_START_PATH ] ; then
    echo "Running script $PRE_START_PATH"
    . "$PRE_START_PATH"
else 
    echo "There is no script $PRE_START_PATH"
fi

# Start Gunicorn
exec gunicorn -k "$WORKER_CLASS" -c "$GUNICORN_CONF" "$APP_MODULE" --preload
