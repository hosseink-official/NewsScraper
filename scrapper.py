import os
import logging


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
# Ensure logger writes to the scrapper.log inside the specified directory
logfile = os.path.abspath(os.path.join(directory, 'scrapper.log'))
# add file handler if not already configured for this logfile
has_handler = False
for h in logger.handlers:
    if isinstance(h, logging.FileHandler) and os.path.abspath(getattr(h, 'baseFilename', '')) == logfile:
        has_handler = True
        break
if not has_handler:
    fh = logging.FileHandler(logfile)
    fh.setLevel(logging.INFO)
    fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(fmt)
    logger.addHandler(fh)

def list_json_files(directory="."):
    """Return a list of .json files in the specified directory.

    Also create or append logs to <directory>/scrapper.log.
    """
    if not os.path.isdir(directory):
        logger.critical(f"Directory does not exist: {directory}")
        raise ValueError(f"Directory does not exist: {directory}")

  

    files = [
        entry for entry in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, entry)) and entry.lower().endswith('.json')
    ]
    logger.info('Found %d json files in %s', len(files), directory)
    return files


if __name__ == '__main__':
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else '.'
    print(list_json_files(path))
