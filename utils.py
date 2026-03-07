import requests
import subprocess
import json
import os
import time
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger("astrbot")

def strip_html(html_content):
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, 'html.parser')
    return soup.get_text()

def fetch_hextech_data_from_url(url="https://apexlol.info/assets/chunks/data.Bq-2u7uT.js"):
    """
    Fetches Hextech data from the given JS file URL.
    Uses Node.js to parse the JS object 'Wi'.
    """
    logger.info(f"Fetching Hextech data from {url}...")
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        content = response.text
    except Exception as e:
        logger.error(f"Failed to download Hextech data: {e}")
        return None

    # Extract the script part starting from 'const Ei=' (Hero data) to include 'Wi=' (Hextech data)
    # We assume 'Wi' is defined after 'Ei' or at least in the same block.
    # To be safe, we try to find 'Wi=[' directly.
    
    start_marker = "Wi=["
    start_index = content.find(start_marker)
    if start_index == -1:
        logger.error("Could not find 'Wi=[' in the data file.")
        return None
    
    # We need to extract enough context to be valid JS, or just the Wi variable.
    # Since Wi might rely on imports (though unlikely for data), we'll try to isolate it.
    # However, 'Wi' definition might end with a comma if it's in a list of declarations.
    # Strategy: Construct a valid JS script that outputs Wi.
    
    # We'll take everything from 'Wi=[' until the end of the file, 
    # but strip the export statement.
    
    script_part = content[start_index:]
    
    # Find export to cut off
    export_index = script_part.rfind("export")
    if export_index != -1:
        script_part = script_part[:export_index]
    
    # Now script_part starts with "Wi=[...],..." or "Wi=[...];"
    # We want to assign it to a variable and print it.
    # Since we started at "Wi=[", we can just prepend "const " or just let it be.
    # But wait, if it's "Wi=[...],Ki=...", we need to handle the trailing parts.
    # Actually, we can just output `console.log(JSON.stringify(Wi))` if we can make the code valid.
    # If we define `Wi` as a global or var, it works.
    
    # Let's prepend "var " to make it "var Wi=[..."
    # And we need to make sure we don't have syntax errors from trailing commas or other variables.
    # If the file structure is `const Ei=[...],Wi=[...],...;`, then taking from `Wi=[` gives `Wi=[...],...;`.
    # If we prepend `var `, it becomes `var Wi=[...],...;`.
    # But `...` might be `Ki=[...]`. If we don't declare `Ki`, it might error?
    # No, `var a=1, b=2;` is valid.
    # But if `Ki` uses something not defined, it might error.
    # However, we only care about `Wi`.
    # Let's try to wrap it in a try-catch or just execute it.
    
    # We also need to handle the end. The file ends with `;`.
    # So `script_part` should be valid JS statements.
    
    js_script = f"var {script_part}\nconsole.log(JSON.stringify(Wi));"
    
    temp_js_file = f"temp_hex_{int(time.time())}.js"
    try:
        with open(temp_js_file, "w", encoding="utf-8") as f:
            f.write(js_script)
            
        result = subprocess.run(
            ["node", temp_js_file], 
            capture_output=True, 
            text=True, 
            encoding="utf-8",
            check=True
        )
        
        json_data = result.stdout.strip()
        data = json.loads(json_data)
        return data
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Node execution failed: {e.stderr}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON output: {e}")
        return None
    except Exception as e:
        logger.error(f"Error processing Hextech data: {e}")
        return None
    finally:
        if os.path.exists(temp_js_file):
            try:
                os.remove(temp_js_file)
            except:
                pass
