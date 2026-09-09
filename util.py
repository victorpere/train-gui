import json

def load_data_from_file(filename):
    """Load data from a JSON file."""
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        raise FileNotFoundError(f"File {filename} not found.")
    except Exception as e:
        raise Exception(f"Error loading data from {filename}: {e}")