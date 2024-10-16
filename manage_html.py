import re
import requests
import inspect
import json
import csv
import platform
import psutil
from pathlib import Path
from duckduckgo_search import DDGS, AsyncDDGS
from bs4 import BeautifulSoup
import ast
import sys
import io

class Tools:
    def __init__(self, default_path):
        self.tools = {}
        self.default_path = Path(default_path)

        self.add_tool(self.ddg_search, "DDGSearch", "Use DDG to search the web for the topic.")
        self.add_tool(self.get_web_page, "GetWebPage", "Get the contents of a web page. Only call this with a valid URL.")
        self.add_tool(self.open_file, "OpenFile", "Open a chosen file.")
        self.add_tool(self.save_file_with_code, "SaveFileWithCode", "Create and save a new file with code.")
        self.add_tool(self.list_directory, "ListDirectory", "List contents of a directory.")
        self.add_tool(self.read_json, "ReadJSON", "Read and parse a JSON file.")
        self.add_tool(self.read_csv, "ReadCSV", "Read and parse a CSV file.")
        self.add_tool(self.get_system_info, "GetSystemInfo", "Get information about the system.")
        self.add_tool(self.get_file_info, "GetFileInfo", "Get information about a file.")
        self.add_tool(self.execute_python_code, "ExecutePythonCode", "Execute Python code and return the output.")

    def add_tool(self, func, name, desc):
        self.tools[name] = {
            "params": list(inspect.signature(func).parameters.keys()),
            "desc": desc,
            "func": func
        }

    def get_tool_list_for_prompt(self):
        return "\n".join(f"* {name}[ {','.join(tool['params'])} ] - {tool['desc']}" for name, tool in self.tools.items())

    async def run_tool(self, name, params):
        if name not in self.tools:
            yield f"{name}[] is not a valid tool"
    
        tool = self.tools[name]
        params = [param.strip('"') for param in params] if isinstance(params, list) else params.strip('"')
        
        try:
            result = tool["func"](params)
            yield result
        except Exception as e:
            yield f"Error running tool {name}: {str(e)}"

    async def execute_python_code(self, code):
        try:
            # Security check: Disallow potentially harmful operations
            forbidden_modules = ['os', 'sys', 'subprocess', 'shutil']
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in forbidden_modules:
                            raise ValueError(f"Importing {alias.name} is not allowed for security reasons.")
                elif isinstance(node, ast.ImportFrom):
                    if node.module in forbidden_modules:
                        raise ValueError(f"Importing from {node.module} is not allowed for security reasons.")

            # Redirect stdout to capture print outputs
            old_stdout = sys.stdout
            redirected_output = sys.stdout = io.StringIO()

            # Execute the code
            exec(code)

            # Restore stdout
            sys.stdout = old_stdout

            yield redirected_output.getvalue()
        except ImportError as e:
            yield f"Error: Required module not installed. {str(e)}"
        except Exception as e:
            yield f"Error executing code: {str(e)}"
        
    def get_url(self, url):
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }
        try:
            response = requests.get(url, headers=headers)
            return response.text
        except Exception as e:
            print(e)
            return "Error retrieving web page"

    async def ddg_search(self, topic):
        topic = " ".join(topic) if isinstance(topic, list) else str(topic)
        full_html = AsyncDDGS().text(topic, max_results=10)
        
        results = []
        for result in full_html:
            results.append(f"Title: {result['title']}\nURL: {result['href'].replace('#', '{{#}}')}\nSnippet: {result['body']}\n***")  

        yield "\n".join(results)

    def get_web_page(self, url):
        try:
            if isinstance(url, list):
                url = url[0]
            full_html = self.get_url(url)
            return self.distill_html(full_html) if full_html else "Error retrieving web page"
        except Exception as e:  
            print(e)
            return "Error retrieving web page"

    def open_file(self, filename):
        try:
            with open(self.default_path / filename, "r") as file:
                return file.read()
        except Exception as e:
            return f"Error opening file '{filename}': {str(e)}"

    async def save_file_with_code(self, filename, code):
        try:
            file_path = self.default_path / filename
            if not file_path.parent.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)
            print(f"Saving code to file: {filename} at {file_path}")
            with open(file_path, "w") as file:
                file.write(code)
            yield f"File '{filename}' created successfully"
        except Exception as e:
            yield f"Error creating file '{filename}': {str(e)}"
        
    def distill_html(self, raw_html):
        try:
            soup = BeautifulSoup(raw_html, 'html.parser')
            return re.sub(r'\s+', ' ', soup.get_text()).strip()
        except Exception as e:
            print(e)
            return "Error distilling HTML"

    def list_directory(self, path="."):
        try:
            full_path = self.default_path / path
            return "\n".join(str(item) for item in full_path.iterdir())
        except Exception as e:
            return f"Error listing directory '{path}': {str(e)}"

    def read_json(self, filename):
        try:
            with open(self.default_path / filename, "r") as file:
                data = json.load(file)
            return json.dumps(data, indent=2)
        except Exception as e:
            return f"Error reading JSON file '{filename}': {str(e)}"

    def read_csv(self, filename, num_rows=5):
        try:
            with open(self.default_path / filename, "r", newline="") as file:
                reader = csv.reader(file)
                headers = next(reader)
                rows = [headers] + [next(reader) for _ in range(min(num_rows, sum(1 for _ in reader)))]
            return "\n".join([",".join(row) for row in rows])
        except Exception as e:
            return f"Error reading CSV file '{filename}': {str(e)}"

    def get_system_info(self, *args):
        try:
            info = {
                "OS": platform.system(),
                "OS Version": platform.version(),
                "Machine": platform.machine(),
                "Processor": platform.processor(),
                "Python Version": platform.python_version(),
                "Total RAM": f"{psutil.virtual_memory().total / (1024**3):.2f} GB",
                "Available RAM": f"{psutil.virtual_memory().available / (1024**3):.2f} GB",
                "CPU Usage": f"{psutil.cpu_percent()}%",
                "Disk Usage": f"{psutil.disk_usage('/').percent}%"
            }
            return json.dumps(info, indent=2)
        except Exception as e:
            return f"Error getting system info: {str(e)}"

    def get_file_info(self, filename):
        try:
            file_path = self.default_path / filename
            stats = file_path.stat()
            info = {
                "Name": file_path.name,
                "Size": f"{stats.st_size} bytes",
                "Created": stats.st_ctime,
                "Modified": stats.st_mtime,
                "Accessed": stats.st_atime,
                "Is Directory": file_path.is_dir(),
                "Is File": file_path.is_file(),
                "Is Symlink": file_path.is_symlink(),
            }
            return json.dumps(info, indent=2)
        except Exception as e:
            return f"Error getting file info for '{filename}': {str(e)}"