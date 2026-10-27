The current environment is a development container. Work in /workspace.
This base profile supplies Pi, Node.js, Git, system Python (python3), and common
command-line tools. It does not create an application Python virtual environment.
A .venv visible inside /workspace may have been created on the host with different
absolute paths or a different Python version. Do not assume it is usable here.
Use HTTP_PROXY/HTTPS_PROXY when present. In allowlist mode only listed hostnames
and ports are reachable; unrestricted mode uses ordinary container networking.
