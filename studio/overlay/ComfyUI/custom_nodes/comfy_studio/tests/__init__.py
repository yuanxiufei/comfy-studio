"""comfy_studio 引擎侧（后端）的自检。

跑法（在包父目录 `custom_nodes/` 下，用引擎的 venv）：:

    cd ComfyUI/custom_nodes
    ..\\..\\.venv\\Scripts\\python.exe -m unittest discover -s comfy_studio/tests -t . -v

只有 ``test_mcp_stdio.py`` 需要 venv 里的解释器（它要真起子进程）；缺了整组跳过。
"""
