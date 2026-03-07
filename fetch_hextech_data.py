import requests
import re
import os
import subprocess
import json

url = "https://apexlol.info/assets/chunks/data.Bq-2u7uT.js"
print(f"Fetching {url}...")
try:
    response = requests.get(url)
    response.raise_for_status()
    content = response.text
except Exception as e:
    print(f"Failed to fetch data: {e}")
    exit(1)

# Remove imports
# The file starts with import ... from ...;
# We can just remove lines starting with import or containing "from" if it's the first line.
# Or just remove everything before "const Ei=".
start_index = content.find("const Ei=")
if start_index == -1:
    print("Could not find 'const Ei=' in content")
    exit(1)

script_content = content[start_index:]

# Remove export statement
# export{Ki as a,Ei as c,Ni as e,Wi as h,Ii as i,Oi as m};
# We'll just truncate at "export"
export_index = script_content.rfind("export")
if export_index != -1:
    script_content = script_content[:export_index]

# Add print statement
script_content += "\nconsole.log(JSON.stringify(Wi, null, 2));"

# Save to temp file
temp_file = "temp_hextech_script.js"
with open(temp_file, "w", encoding="utf-8") as f:
    f.write(script_content)

print("Running node script...")
try:
    # Run node
    result = subprocess.run(["node", temp_file], capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        print("Node execution failed:")
        print(result.stderr)
    else:
        # Save JSON
        with open("hextech_data.json", "w", encoding="utf-8") as f:
            f.write(result.stdout)
        print("Successfully saved hextech_data.json")
        
        # Parse and print stats
        data = json.loads(result.stdout)
        print(f"Found {len(data)} hextech entries")
        
except Exception as e:
    print(f"Error running node: {e}")
finally:
    if os.path.exists(temp_file):
        os.remove(temp_file)
