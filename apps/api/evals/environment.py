import os


def configure_local_evaluation() -> None:
    # Set before importing DeepEval. Existing cloud login and dotenv files must not
    # turn a local fixture check into telemetry, uploads or a default-model call.
    os.environ.update(
        {
            "DEEPEVAL_TELEMETRY_OPT_OUT": "1",
            "DEEPEVAL_DISABLE_DOTENV": "1",
            "DEEPEVAL_DISABLE_LEGACY_KEYFILE": "1",
            "DEEPEVAL_FILE_SYSTEM": "READ_ONLY",
            "DEEPEVAL_RETRY_MAX_ATTEMPTS": "1",
            "DEEPEVAL_VERBOSE_MODE": "0",
            "DEEPEVAL_LOG_STACK_TRACES": "0",
            "CONFIDENT_API_KEY": "",
            "CONFIDENT_OPEN_BROWSER": "0",
            "ENABLE_DEEPEVAL_CACHE": "0",
            "IGNORE_DEEPEVAL_ERRORS": "0",
            "SKIP_DEEPEVAL_MISSING_PARAMS": "0",
        }
    )
