import re
import datetime
import gradio as gr
import logging
from dotenv import load_dotenv
from pathlib import Path
from llm_manager import get_llm
from manage_html import Tools
from gradio_log import Log

logger = logging.getLogger(__name__)
#save log to file
log_file = "C:/Code/0602/gradio_log.txt"

load_dotenv()

SYSTEM_MESSAGE_TEMPLATE = "prompt_template.txt"
UPLOAD_MESSAGE_TEMPLATE = "uploaded_file_prompt.txt"
TOOL_REGEX = r'(<tool>[a-zA-Z0-9_]+</tool>.*?</tool_input>)'    
TOOL_TAG = r'<tool>([a-zA-Z0-9_]+)</tool>'
TOOL_INPUT = r'<tool_input>(.*?)</tool_input>'
CODE_REGEX = r'(<code>(.*?)</code>)|(```python\s(.*?)```) |(```html\s(.*?)```) |(```css\s(.*?)```) |(```javascript\s(.*?)```)'
SAVE_FILE_REGEX = r'<tool>SaveFileWithCode</tool>\s*<tool_input>(.*?)</tool_input>\s*```(\S+?)\n(.*?)```'


class CodeAnalyzer:
    def __init__(self, model, temperature, default_path):
        self.model = model
        self.temperature = temperature
        self.default_path = Path(default_path)
        self.llm_tools = Tools(default_path)

    def create_message(self, template):
        with open(template) as f:
            message = f.read()

        now = datetime.datetime.now()
        current_date = now.strftime("%B %d, %Y")

        message = message.replace("{{CURRENT_DATE}}", current_date)
        message = message.replace("{{TOOLS_PROMPT}}", self.llm_tools.get_tool_list_for_prompt())
        message = message.replace("{{default_path}}", str(self.default_path))

        return message

    async def retry_code(self, code_content, execution_result, filename):

            fix_prompt = f"""
            The improved code you provided has errors. Please fix the following code:
            
            ```python
            {code_content}
            ```
            
            Error:
            {execution_result}
            
            You must return the code using the tool calling format of:
            <tool>SaveFileWithCode</tool>
            <tool_input>filename.extension</tool_input>
            ```python
            fixed_code
            ```

            """
            logger.info(f"Requesting final fix for {filename}")
            async for chunk in self.model.get_aresponse(fix_prompt):
                
                yield chunk
            
            fixed_code = re.search(CODE_REGEX, chunk, re.DOTALL)
            if fixed_code:
                fixed_code = fixed_code.group(1)
                logger.info(f"Saving and executing final fixed code for {filename}")
                yield "Saving and executing final fixed code:\n"
                async for save_result in self.llm_tools.save_file_with_code(filename, fixed_code.strip()):
                    yield f"{save_result}\n"
                async for final_execution_result in self.llm_tools.execute_python_code(fixed_code.strip()):
                    logger.info(f"Final execution result for {filename}: {final_execution_result}")
                    yield f"Final Execution result:\n{final_execution_result}\n"

    async def process_completion(self, completion):
        logger.info(f"Processing completion: {completion[:100]}...")  # Log first 100 chars for brevity
        yield f"\n\nLLM Output:\n{completion}\n"

        # Handle SaveFileWithCode tool explicitly
        save_file_segments = re.findall(SAVE_FILE_REGEX, completion, re.DOTALL)
        for filename, code_type, code_content in save_file_segments:
            async for chunk in self.process_tool("SaveFileWithCode", [filename, code_content], code_content, code_type, set()):
                yield chunk

        # Handle other code blocks
        code_blocks = re.findall(CODE_REGEX, completion, re.DOTALL)
        for i, (_, code_type, code_content) in enumerate(code_blocks):
            if not code_type:
                code_type = self.detect_code_type(code_content)
            
            # Only save and execute code blocks that weren't handled by SaveFileWithCode
            if not any(code_content.strip() in segment for segment in save_file_segments):
                filename = f"code_block_{i+1}.{code_type}"
                logger.info(f"Saving code block {i+1} to {filename}")
                async for save_result in self.llm_tools.save_file_with_code(filename, code_content.strip()):
                    yield f"\nSaved code block {i+1} to {filename}: {save_result}\n"

                if code_type.lower() == 'python':
                    yield f"Executing Python code from {filename}:\n"
                    async for execution_result in self.llm_tools.execute_python_code(code_content.strip()):
                        logger.info(f"Execution result for {filename}: {execution_result}")
                        yield f"Execution result:\n{execution_result}\n"

        # Handle other tools
        tool_segments = re.findall(TOOL_REGEX, completion, re.DOTALL)
        for segment in tool_segments:
            tool = re.search(TOOL_TAG, segment).group(1)
            params = re.findall(TOOL_INPUT, segment, re.DOTALL)
            if tool != "SaveFileWithCode":  # We've already handled SaveFileWithCode
                logger.info(f"Processing tool: {tool}")
                async for chunk in self.process_tool(tool, params, "", "", set()):
                    yield chunk

        logger.info("Processing complete")
        yield "\nProcessing complete. Ready for next input.\n"

    async def generate(self, message, history):
        logger.info(f"Generating response for: {message}")
        if message:
            sys_template = self.create_message(SYSTEM_MESSAGE_TEMPLATE)
            prompt = f"User Input: {message}\n\n + {sys_template}\n\nHistory of chat: {history}\n\n"
            
            # Collect full response from get_aresponse
            full_response = ""
            async for chunk in self.model.get_aresponse(prompt):
                full_response += chunk
                yield full_response  # Yield intermediate results
            
            # Collect final response from process_completion
            final_response = ""
            async for chunk in self.process_completion(full_response):
                final_response += chunk
            
            yield final_response  # Yield the final result
        else:
            yield "No input provided. Please enter a text message."
        logger.info("Generation complete")

    def detect_code_type(self, line):
        if 'import ' in line or 'def ' in line or 'class ' in line:
            return 'python'
        elif '<html>' in line or '<body>' in line:
            return 'html'
        elif 'SELECT ' in line or 'INSERT ' in line:
            return 'sql'
        elif 'function ' in line or 'var ' in line or 'const ' in line:
            return 'javascript'
        elif '{' in line and '}' in line and ':' in line:
            return 'css'
        return ""

    async def process_tool(self, tool, params, code_block, code_type, saved_files):
        logger.info(f"Processing tool: {tool}")
        result = ""

        try:
            if tool == "SaveFileWithCode":
                filename = params[0] if params else 'default_filename.py'
                code_content = params[1] if len(params) > 1 else code_block

                # Ensure the filename has an extension
                if not Path(filename).suffix:
                    filename += '.py'

                full_filename = self.default_path / filename

                if not code_content.strip():
                    logger.error(f"Attempted to save empty file: {full_filename}")
                    
                async for result in self.llm_tools.save_file_with_code(str(full_filename), code_content.strip()):
                    logger.info(f"Save result for {full_filename}: {result}")
                    yield f"\nFile '{full_filename}' created successfully\n"
                saved_files.add(code_content)


            elif tool == "ExecutePythonCode":
                code_content = params[0] if params else code_block
                async for execution_result in self.llm_tools.execute_python_code(code_content.strip()):
                    logger.info(f"Execution result for ExecutePythonCode: {execution_result}")
                    yield f"Execution result:\n{execution_result}\n"
                    if "Error" in execution_result:
                        # Use async for to iterate over the asynchronous generator
                        async for chunk in self.retry_code(code_content, execution_result, "executed_code.py"):
                            yield chunk 

            elif tool == "OpenFile":
                filename = params[0] if params else None
                result = self.llm_tools.open_file(filename) if filename else "Filename not provided."

            elif tool == "DDGSearch":
                query = params[0] if params else ""
                async for result in self.llm_tools.ddg_search(query):
                    yield f"Search results:\n{result}\n"

            elif tool == "GetWebPage":
                url = params[0] if params else ""
                result = self.llm_tools.get_web_page(url)

            else:
                result = self.llm_tools.run_tool(tool, params)

        except Exception as e:
            logger.error(f"Error processing tool {tool}: {str(e)}")
            result = f"Error processing tool {tool}: {str(e)}"

        logger.info(f"Tool result: {result}")
        yield f"Tool result:\n{result}\n"

    async def analyze_code(self, file_contents):
        prompt = f"User Input: Analyze this code, fix it, and save it accordingly using the tools provided to you.\n\nCode:\n```{file_contents}```\n\n + {UPLOAD_MESSAGE_TEMPLATE}\n\n"
        async for chunk in self.model.get_aresponse(prompt):
            yield chunk
        async for chunk in self.process_completion(chunk):
            yield chunk

    
with gr.Blocks() as demo:

    model = get_llm("ollama", "llama3.1:8b-instruct-q8_0")
    code_analyzer = CodeAnalyzer(model, temperature=0.1, default_path=Path("code"))

    async def chat_function(message, history):
        async for response in code_analyzer.generate(message, history):
            yield response

    interface = gr.ChatInterface(
        chat_function,
        chatbot=gr.Chatbot(height=600, placeholder="Chat with the Coding Assistant..."),
        textbox=gr.Textbox(placeholder="Type your message here...", container=False, scale=7),
        title="Coding Assistant",
        description="Ask questions about coding, debugging, or any programming topic!",
        theme="soft",
        retry_btn="Retry",
        undo_btn="Undo",
        clear_btn="Clear",
    )



demo.launch(debug=True, share=False, show_error=True)