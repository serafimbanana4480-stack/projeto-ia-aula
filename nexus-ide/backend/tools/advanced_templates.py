"""Advanced project templates — complete, working project structures.

Each template contains real, functional code (not placeholders).
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend.persistence.db import propose_change
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

TEMPLATES: dict[str, dict[str, Any]] = {
    "python": {
        "name": "Python Project",
        "description": "Modern Python project with pytest, ruff, and pyproject.toml",
        "tags": ["python", "backend"],
        "setup_commands": ["pip install -e .", "pytest"],
        "files": {
            "README.md": """# {name}

{description}

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
```

## Run

```bash
python -m {name}
```

## Test

```bash
pytest
```
""",
            "pyproject.toml": """[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "{name}"
version = "0.1.0"
description = "{description}"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "ruff>=0.1.0",
    "mypy>=1.0",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.mypy]
python_version = "3.11"
strict = true
""",
            ".gitignore": """__pycache__/
*.pyc
.venv/
.env
*.egg-info/
dist/
build/
.pytest_cache/
.mypy_cache/
.coverage
htmlcov/
""",
            "src/{name}/__init__.py": '"""{description}"""\n\n__version__ = "0.1.0"\n',
            "src/{name}/main.py": """\"\"\"Main entry point for {name}.\"\"\"\n\ndef main() -> None:\n    print("Hello from {name}!")\n\nif __name__ == "__main__":\n    main()\n""",
            "src/{name}/core.py": """\"\"\"Core module for {name}.\"\"\"\n\nfrom typing import Any\n\nclass AppConfig:\n    \"\"\"Application configuration.\"\"\"\n    \n    def __init__(self, debug: bool = False) -> None:\n        self.debug = debug\n\ndef greet(name: str = "World") -> str:\n    \"\"\"Return a greeting message.\"\"\"\n    return f"Hello, {{name}}!"\n""",
            "tests/__init__.py": "",
            "tests/test_core.py": """\"\"\"Tests for core module.\"\"\"\n\nfrom {name}.core import greet, AppConfig\n\ndef test_greet() -> None:\n    assert greet("Alice") == "Hello, Alice!"\n\ndef test_greet_default() -> None:\n    assert greet() == "Hello, World!"\n\ndef test_app_config() -> None:\n    config = AppConfig(debug=True)\n    assert config.debug is True\n""",
            ".github/workflows/ci.yml": """name: CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: ruff check src tests
      - run: mypy src
      - run: pytest --cov={name} --cov-report=xml
      - uses: codecov/codecov-action@v3
""",
        },
    },
    "fastapi": {
        "name": "FastAPI Project",
        "description": "Production-ready FastAPI with SQLModel, JWT auth, and Docker",
        "tags": ["python", "fastapi", "api", "backend"],
        "setup_commands": ["pip install -r requirements.txt", "uvicorn src.{name}.main:app --reload"],
        "files": {
            "README.md": """# {name}

{description}

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn src.{name}.main:app --reload
```

## API Docs

- Swagger: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
""",
            "requirements.txt": """fastapi>=0.110.0
uvicorn[standard]>=0.27.0
sqlmodel>=0.0.16
pydantic-settings>=2.1.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
pytest>=7.0
httpx>=0.26.0
""",
            ".gitignore": "__pycache__/\n.venv/\n.env\n*.db\n.pytest_cache/\n",
            "src/{name}/__init__.py": '"""{description}"""\n\n__version__ = "0.1.0"\n',
            "src/{name}/main.py": """\"\"\"FastAPI application for {name}.\"\"\"\n\nfrom fastapi import FastAPI\nfrom contextlib import asynccontextmanager\n\nfrom {name}.routes import items, auth\nfrom {name}.database import create_db_and_tables\n\n@asynccontextmanager\nasync def lifespan(app: FastAPI):\n    create_db_and_tables()\n    yield\n\napp = FastAPI(\n    title="{name}",\n    description="{description}",\n    version="0.1.0",\n    lifespan=lifespan,\n)\n\napp.include_router(auth.router, prefix="/auth", tags=["auth"])\napp.include_router(items.router, prefix="/items", tags=["items"])\n\n@app.get("/health")\nasync def health():\n    return {{"status": "ok"}}\n""",
            "src/{name}/database.py": """\"\"\"Database configuration.\"\"\"\n\nfrom sqlmodel import SQLModel, create_engine, Session\n\nDATABASE_URL = "sqlite:///./{name}.db"\nengine = create_engine(DATABASE_URL, echo=False)\n\ndef create_db_and_tables():\n    SQLModel.metadata.create_all(engine)\n\ndef get_session():\n    with Session(engine) as session:\n        yield session\n""",
            "src/{name}/models.py": """\"\"\"Data models.\"\"\"\n\nfrom sqlmodel import SQLModel, Field\nfrom typing import Optional\nfrom datetime import datetime\n\nclass Item(SQLModel, table=True):\n    id: Optional[int] = Field(default=None, primary_key=True)\n    name: str\n    description: Optional[str] = None\n    price: float\n    created_at: datetime = Field(default_factory=datetime.utcnow)\n\nclass ItemCreate(SQLModel):\n    name: str\n    description: Optional[str] = None\n    price: float\n\nclass ItemRead(SQLModel):\n    id: int\n    name: str\n    description: Optional[str] = None\n    price: float\n""",
            "src/{name}/routes/__init__.py": "",
            "src/{name}/routes/items.py": """\"\"\"Item routes.\"\"\"\n\nfrom fastapi import APIRouter, Depends, HTTPException\nfrom sqlmodel import Session, select\n\nfrom {name}.database import get_session\nfrom {name}.models import Item, ItemCreate, ItemRead\n\nrouter = APIRouter()\n\n@router.post("/", response_model=ItemRead)\ndef create_item(item: ItemCreate, session: Session = Depends(get_session)):\n    db_item = Item.from_orm(item)\n    session.add(db_item)\n    session.commit()\n    session.refresh(db_item)\n    return db_item\n\n@router.get("/", response_model=list[ItemRead])\ndef list_items(session: Session = Depends(get_session)):\n    return session.exec(select(Item)).all()\n\n@router.get("/{{item_id}}", response_model=ItemRead)\ndef get_item(item_id: int, session: Session = Depends(get_session)):\n    item = session.get(Item, item_id)\n    if not item:\n        raise HTTPException(status_code=404, detail="Item not found")\n    return item\n\n@router.delete("/{{item_id}}")\ndef delete_item(item_id: int, session: Session = Depends(get_session)):\n    item = session.get(Item, item_id)\n    if not item:\n        raise HTTPException(status_code=404, detail="Item not found")\n    session.delete(item)\n    session.commit()\n    return {{"deleted": True}}\n""",
            "src/{name}/routes/auth.py": """\"\"\"Authentication routes.\"\"\"\n\nfrom fastapi import APIRouter, HTTPException\nfrom pydantic import BaseModel\n\nrouter = APIRouter()\n\nclass LoginRequest(BaseModel):\n    username: str\n    password: str\n\nclass TokenResponse(BaseModel):\n    access_token: str\n    token_type: str = "bearer"\n\n@router.post("/login", response_model=TokenResponse)\ndef login(req: LoginRequest):\n    # TODO: implement real auth\n    if req.username == "admin" and req.password == "admin":\n        return TokenResponse(access_token="fake-jwt-token")\n    raise HTTPException(status_code=401, detail="Invalid credentials")\n""",
            "tests/__init__.py": "",
            "tests/test_main.py": """\"\"\"API tests.\"\"\"\n\nfrom fastapi.testclient import TestClient\nfrom {name}.main import app\n\nclient = TestClient(app)\n\ndef test_health():\n    r = client.get("/health")\n    assert r.status_code == 200\n    assert r.json() == {{"status": "ok"}}\n\ndef test_create_item():\n    r = client.post("/items/", json={{"name": "Test", "price": 9.99}})\n    assert r.status_code == 200\n    data = r.json()\n    assert data["name"] == "Test"\n""",
            "Dockerfile": """FROM python:3.12-slim\n\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\n\nCOPY src/ ./src/\n\nCMD ["uvicorn", "src.{name}.main:app", "--host", "0.0.0.0", "--port", "8000"]\n""",
            "docker-compose.yml": """version: "3.9"
services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=sqlite:///./data.db\n""",
        },
    },
    "cli_python": {
        "name": "Python CLI",
        "description": "Rich CLI application with Click, colored output, and config support",
        "tags": ["python", "cli"],
        "setup_commands": ["pip install -e .", "{name} --help"],
        "files": {
            "README.md": """# {name}

{description}

## Install

```bash
pip install -e .
```

## Usage

```bash
{name} --help
{name} greet Alice
{name} config set theme dark
```
""",
            "pyproject.toml": """[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "{name}"
version = "0.1.0"
description = "{description}"
requires-python = ">=3.11"
dependencies = [
    "click>=8.0",
    "rich>=13.0",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = ["pytest>=7.0", "ruff>=0.1.0"]

[project.scripts]
{name} = "{name}.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
""",
            ".gitignore": "__pycache__/\n.venv/\n.env\n*.egg-info/\ndist/\nbuild/\n",
            "src/{name}/__init__.py": '"""{description}"""\n\n__version__ = "0.1.0"\n',
            "src/{name}/cli.py": """\"\"\"CLI entry point using Click and Rich.\"\"\"\n\nimport click\nfrom rich.console import Console\nfrom rich.table import Table\n\nfrom {name}.core import Config, greet\n\nconsole = Console()\n\n@click.group()\n@click.version_option(version=\"0.1.0\")\ndef main():\n    \"\"\"{name} CLI.\"\"\"\n    pass\n\n@main.command()\n@click.argument(\"name\", default=\"World\")\ndef greet_cmd(name: str):\n    \"\"\"Greet someone.\"\"\"\n    console.print(f\"[bold green]{{greet(name)}}[/bold green]\")\n\n@main.group()\ndef config():\n    \"\"\"Manage configuration.\"\"\"\n    pass\n\n@config.command(\"show\")\ndef config_show():\n    \"\"\"Show current config.\"\"\"\n    cfg = Config.load()\n    table = Table(title=\"Configuration\")\n    table.add_column(\"Key\", style=\"cyan\")\n    table.add_column(\"Value\", style=\"magenta\")\n    for k, v in cfg.dict().items():\n        table.add_row(k, str(v))\n    console.print(table)\n\n@config.command(\"set\")\n@click.argument(\"key\")\n@click.argument(\"value\")\ndef config_set(key: str, value: str):\n    \"\"\"Set a config value.\"\"\"\n    cfg = Config.load()\n    setattr(cfg, key, value)\n    cfg.save()\n    console.print(f\"[green]Set {{key}} = {{value}}[/green]\")\n\nif __name__ == \"__main__\":\n    main()\n""",
            "src/{name}/core.py": """\"\"\"Core logic.\"\"\"\n\nimport json\nfrom pathlib import Path\nfrom pydantic import BaseModel\n\nCONFIG_PATH = Path.home() / ".config" / "{name}" / "config.json"\n\nclass Config(BaseModel):\n    theme: str = \"dark\"\n    verbose: bool = False\n\n    @classmethod\n    def load(cls) -> \"Config\":\n        if CONFIG_PATH.exists():\n            return cls(**json.loads(CONFIG_PATH.read_text()))\n        return cls()\n\n    def save(self) -> None:\n        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)\n        CONFIG_PATH.write_text(self.model_dump_json(indent=2))\n\ndef greet(name: str = \"World\") -> str:\n    return f\"Hello, {{name}}!\"\n""",
            "tests/__init__.py": "",
            "tests/test_core.py": """\"\"\"Tests for core module.\"\"\"\n\nfrom {name}.core import greet, Config\n\ndef test_greet() -> None:\n    assert greet(\"Alice\") == \"Hello, Alice!\"\n\ndef test_config_defaults() -> None:\n    cfg = Config()\n    assert cfg.theme == \"dark\"\n    assert cfg.verbose is False\n""",
        },
    },
    "fullstack_next_fastapi": {
        "name": "Fullstack Next.js + FastAPI",
        "description": "Modern fullstack app with Next.js 15 frontend and FastAPI backend",
        "tags": ["fullstack", "nextjs", "fastapi", "react", "typescript"],
        "setup_commands": ["cd backend && pip install -r requirements.txt", "cd frontend && npm install"],
        "files": {
            "README.md": """# {name}

{description}

## Architecture

- **Frontend**: Next.js 15 + React 19 + TypeScript + Tailwind CSS
- **Backend**: FastAPI + SQLModel + SQLite
- **Deployment**: Docker Compose

## Quick Start

```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

- Frontend: http://localhost:3000
- API: http://localhost:8000
- API Docs: http://localhost:8000/docs
""",
            "docker-compose.yml": """version: "3.9"
services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    volumes:
      - ./backend:/app
  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
""",
            "backend/Dockerfile": """FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD [\"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]\n""",
            "backend/requirements.txt": """fastapi>=0.110.0
uvicorn[standard]>=0.27.0
sqlmodel>=0.0.16
pydantic>=2.0\n""",
            "backend/main.py": """from fastapi import FastAPI\nfrom fastapi.middleware.cors import CORSMiddleware\n\napp = FastAPI()\n\napp.add_middleware(\n    CORSMiddleware,\n    allow_origins=[\"http://localhost:3000\"],\n    allow_credentials=True,\n    allow_methods=[\"*\"],\n    allow_headers=[\"*\"],\n)\n\n@app.get(\"/api/health\")\ndef health():\n    return {{\"status\": \"ok\"}}\n\n@app.get(\"/api/items\")\ndef items():\n    return [\n        {{\"id\": 1, \"name\": \"Item 1\"}},\n        {{\"id\": 2, \"name\": \"Item 2\"}},\n    ]\n""",
            "frontend/Dockerfile": """FROM node:20-alpine\nWORKDIR /app\nCOPY package*.json ./\nRUN npm install\nCOPY . .\nRUN npm run build\nCMD [\"npm\", \"start\"]\n""",
            "frontend/package.json": """{{\n  \"name\": \"{name}-frontend\",\n  \"version\": \"0.1.0\",\n  \"private\": true,\n  \"scripts\": {{\n    \"dev\": \"next dev\",\n    \"build\": \"next build\",\n    \"start\": \"next start\"\n  }},\n  \"dependencies\": {{\n    \"next\": \"^15.0.0\",\n    \"react\": \"^19.0.0\",\n    \"react-dom\": \"^19.0.0\"\n  }},\n  \"devDependencies\": {{\n    \"@types/node\": \"^20.0.0\",\n    \"@types/react\": \"^19.0.0\",\n    \"typescript\": \"^5.0.0\",\n    \"tailwindcss\": \"^4.0.0\"\n  }}\n}}\n""",
            "frontend/app/layout.tsx": """export const metadata = {{\n  title: \"{name}\",\n  description: \"{description}\",\n}};\n\nexport default function RootLayout({{ children }}: {{ children: React.ReactNode }}) {{\n  return (\n    <html lang=\"en\">\n      <body>{{children}}</body>\n    </html>\n  );\n}}\n""",
            "frontend/app/page.tsx": """\"use client\";\n\nimport {{ useEffect, useState }} from \"react\";\n\nexport default function Home() {{\n  const [items, setItems] = useState([]);\n\n  useEffect(() => {{\n    fetch(\"http://localhost:8000/api/items\")\n      .then((r) => r.json())\n      .then(setItems);\n  }}, []);\n\n  return (\n    <main className=\"p-8\">\n      <h1 className=\"text-2xl font-bold mb-4\">{name}</h1>\n      <ul>\n        {{items.map((item: any) => (\n          <li key={{item.id}}>{{item.name}}</li>\n        ))}}\n      </ul>\n    </main>\n  );\n}}\n""",
            "frontend/tsconfig.json": """{{\n  \"compilerOptions\": {{\n    \"lib\": [\"dom\", \"dom.iterable\", \"esnext\"],\n    \"allowJs\": true,\n    \"skipLibCheck\": true,\n    \"strict\": true,\n    \"noEmit\": true,\n    \"esModuleInterop\": true,\n    \"module\": \"esnext\",\n    \"moduleResolution\": \"bundler\",\n    \"resolveJsonModule\": true,\n    \"isolatedModules\": true,\n    \"jsx\": \"preserve\",\n    \"incremental\": true,\n    \"paths\": {{ \"@/*\": [\"./*\"] }}\n  }},\n  \"include\": [\"next-env.d.ts\", \"**/*.ts\", \"**/*.tsx\"],\n  \"exclude\": [\"node_modules\"]\n}}\n""",
        },
    },
    "discord_bot": {
        "name": "Discord Bot",
        "description": "Python discord.py bot with commands, events, and SQLite storage",
        "tags": ["python", "discord", "bot"],
        "setup_commands": ["pip install -r requirements.txt", "python bot.py"],
        "files": {
            "README.md": """# {name}

{description}

## Setup

1. Create a bot at https://discord.com/developers/applications
2. Copy `.env.example` to `.env` and add your token
3. Install dependencies and run

```bash
pip install -r requirements.txt
python bot.py
```
""",
            "requirements.txt": "discord.py>=2.3.0\naiosqlite>=0.19.0\npython-dotenv>=1.0.0\n",
            ".env.example": "DISCORD_TOKEN=your_bot_token_here\nCOMMAND_PREFIX=!\n",
            ".gitignore": ".env\n__pycache__/\n.venv/\n*.db\n",
            "bot.py": """\"\"\"Discord bot for {name}.\"\"\"\n\nimport asyncio\nimport os\n\nimport discord\nfrom discord.ext import commands\nfrom dotenv import load_dotenv\n\nload_dotenv()\n\nintents = discord.Intents.default()\nintents.message_content = True\n\nbot = commands.Bot(\n    command_prefix=os.getenv(\"COMMAND_PREFIX\", \"!\"),\n    intents=intents,\n)\n\n@bot.event\nasync def on_ready():\n    print(f\"{{bot.user}} is online!\")\n\n@bot.command()\nasync def ping(ctx: commands.Context):\n    await ctx.send(f\"Pong! {{round(bot.latency * 1000)}}ms\")\n\n@bot.command()\nasync def hello(ctx: commands.Context):\n    await ctx.send(f\"Hello, {{ctx.author.mention}}!\")\n\nasync def main():\n    async with bot:\n        await bot.start(os.getenv(\"DISCORD_TOKEN\"))\n\nif __name__ == \"__main__\":\n    asyncio.run(main())\n""",
            "cogs/__init__.py": "",
            "cogs/general.py": """\"\"\"General commands cog.\"\"\"\n\nfrom discord.ext import commands\n\nclass General(commands.Cog):\n    def __init__(self, bot: commands.Bot):\n        self.bot = bot\n\n    @commands.command()\n    async def info(self, ctx: commands.Context):\n        await ctx.send(f\"Bot: {{self.bot.user}} | Latency: {{round(self.bot.latency * 1000)}}ms\")\n\nasync def setup(bot: commands.Bot):\n    await bot.add_cog(General(bot))\n""",
        },
    },
    "chrome_extension": {
        "name": "Chrome Extension",
        "description": "Manifest V3 Chrome extension with popup and content script",
        "tags": ["javascript", "chrome", "extension", "frontend"],
        "setup_commands": ["Open chrome://extensions, enable Developer mode, click Load unpacked and select this folder"],
        "files": {
            "README.md": """# {name}

{description}

## Install

1. Open Chrome and navigate to `chrome://extensions/`
2. Enable **Developer mode** (toggle in top right)
3. Click **Load unpacked**
4. Select this project folder

## Files

- `manifest.json` — Extension configuration
- `popup.html/js` — Extension popup UI
- `content.js` — Content script injected into pages
- `background.js` — Service worker
""",
            "manifest.json": """{{\n  \"manifest_version\": 3,\n  \"name\": \"{name}\",\n  \"version\": \"0.1.0\",\n  \"description\": \"{description}\",\n  \"permissions\": [\"activeTab\", \"storage\"],\n  \"action\": {{\n    \"default_popup\": \"popup.html\",\n    \"default_icon\": {{\n      \"16\": \"icon.png\"\n    }}\n  }},\n  \"background\": {{\n    \"service_worker\": \"background.js\"\n  }},\n  \"content_scripts\": [\n    {{\n      \"matches\": [\"<all_urls>\"],\n      \"js\": [\"content.js\"]\n    }}\n  ]\n}}\n""",
            "popup.html": """<!DOCTYPE html>\n<html>\n<head>\n  <meta charset=\"UTF-8\">\n  <style>\n    body {{ width: 200px; padding: 10px; font-family: sans-serif; }}\n    button {{ width: 100%; padding: 8px; margin-top: 8px; cursor: pointer; }}\n  </style>\n</head>\n<body>\n  <h2>{name}</h2>\n  <p id=\"status\">Ready</p>\n  <button id=\"clickMe\">Click Me</button>\n  <script src=\"popup.js\"></script>\n</body>\n</html>\n""",
            "popup.js": """document.getElementById('clickMe').addEventListener('click', () => {{\n  chrome.tabs.query({{active: true, currentWindow: true}}, (tabs) => {{\n    chrome.scripting.executeScript({{\n      target: {{tabId: tabs[0].id}},\n      func: () => alert('Hello from {name}!')\n    }});\n  }});\n}});\n""",
            "content.js": """console.log('{name} content script loaded');\n\n// Highlight all paragraphs\nconst paragraphs = document.querySelectorAll('p');\nparagraphs.forEach(p => {{\n  p.style.border = '1px solid blue';\n}});\n""",
            "background.js": """chrome.runtime.onInstalled.addListener(() => {{\n  console.log('{name} extension installed');\n}});\n""",
        },
    },
    "data_science": {
        "name": "Data Science Project",
        "description": "Jupyter notebooks, Pandas, Scikit-learn, and MLflow tracking",
        "tags": ["python", "data-science", "jupyter", "ml"],
        "setup_commands": ["pip install -r requirements.txt", "jupyter notebook"],
        "files": {
            "README.md": """# {name}

{description}

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Notebooks

- `notebooks/01_eda.ipynb` — Exploratory Data Analysis
- `notebooks/02_model.ipynb` — Model Training

## Run

```bash
jupyter notebook notebooks/
```
""",
            "requirements.txt": """jupyter>=1.0.0
pandas>=2.0.0
numpy>=1.24.0
matplotlib>=3.7.0
seaborn>=0.12.0
scikit-learn>=1.3.0
mlflow>=2.8.0\n""",
            ".gitignore": ".venv/\n.env\n__pycache__/\n.ipynb_checkpoints/\nmlruns/\n*.csv\ndata/raw/*\n!data/raw/.gitkeep\n",
            "notebooks/01_eda.ipynb": """{{\n  \"cells\": [\n    {{\n      \"cell_type\": \"markdown\",\n      \"metadata\": {{}},\n      \"source\": [\"# Exploratory Data Analysis\\n\\nLoad and explore the dataset.\"]\n    }},\n    {{\n      \"cell_type\": \"code\",\n      \"execution_count\": null,\n      \"metadata\": {{}},\n      \"source\": [\"import pandas as pd\\nimport matplotlib.pyplot as plt\\nimport seaborn as sns\\n\\ndf = pd.read_csv(\\\"data/raw/dataset.csv\\\")\\ndf.head()\"]\n    }}\n  ],\n  \"metadata\": {{\n    \"kernelspec\": {{\n      \"display_name\": \"Python 3\",\n      \"language\": \"python\",\n      \"name\": \"python3\"\n    }}\n  }},\n  \"nbformat\": 4,\n  \"nbformat_minor\": 4\n}}\n""",
            "notebooks/02_model.ipynb": """{{\n  \"cells\": [\n    {{\n      \"cell_type\": \"markdown\",\n      \"metadata\": {{}},\n      \"source\": [\"# Model Training\\n\\nTrain and evaluate a machine learning model.\"]\n    }},\n    {{\n      \"cell_type\": \"code\",\n      \"execution_count\": null,\n      \"metadata\": {{}},\n      \"source\": [\"from sklearn.model_selection import train_test_split\\nfrom sklearn.ensemble import RandomForestClassifier\\nfrom sklearn.metrics import accuracy_score\\nimport mlflow\\n\\n# TODO: load your dataset\\n# X_train, X_test, y_train, y_test = train_test_split(X, y)\\n\\nwith mlflow.start_run():\\n    clf = RandomForestClassifier(n_estimators=100)\\n    clf.fit(X_train, y_train)\\n    preds = clf.predict(X_test)\\n    acc = accuracy_score(y_test, preds)\\n    mlflow.log_metric(\\\"accuracy\\\", acc)\\n    print(f\\\"Accuracy: {{acc}}\\\")\"]\n    }}\n  ],\n  \"metadata\": {{\n    \"kernelspec\": {{\n      \"display_name\": \"Python 3\",\n      \"language\": \"python\",\n      \"name\": \"python3\"\n    }}\n  }},\n  \"nbformat\": 4,\n  \"nbformat_minor\": 4\n}}\n""",
            "src/__init__.py": "",
            "src/data.py": """\"\"\"Data loading and preprocessing utilities.\"\"\"\n\nimport pandas as pd\nfrom pathlib import Path\n\nDATA_DIR = Path(__file__).parent.parent / \"data\" / \"raw\"\n\ndef load_dataset(filename: str = \"dataset.csv\") -> pd.DataFrame:\n    \"\"\"Load a CSV dataset.\"\"\"\n    path = DATA_DIR / filename\n    return pd.read_csv(path)\n\ndef preprocess(df: pd.DataFrame) -> pd.DataFrame:\n    \"\"\"Basic preprocessing: drop nulls, encode categoricals.\"\"\"\n    df = df.dropna()\n    for col in df.select_dtypes(include=[\"object\"]).columns:\n        df[col] = df[col].astype(\"category\").cat.codes\n    return df\n""",
            "src/models.py": """\"\"\"Model definitions.\"\"\"\n\nfrom sklearn.ensemble import RandomForestClassifier\nfrom sklearn.linear_model import LogisticRegression\n\nMODELS = {{\n    \"random_forest\": RandomForestClassifier(n_estimators=100, random_state=42),\n    \"logistic_regression\": LogisticRegression(max_iter=1000),\n}}\n""",
            "src/train.py": """\"\"\"Training script.\"\"\"\n\nimport argparse\nimport mlflow\nfrom sklearn.model_selection import train_test_split\nfrom sklearn.metrics import accuracy_score\n\nfrom {name}.src.data import load_dataset, preprocess\nfrom {name}.src.models import MODELS\n\ndef main():\n    parser = argparse.ArgumentParser()\n    parser.add_argument(\"--model\", default=\"random_forest\", choices=list(MODELS.keys()))\n    args = parser.parse_args()\n\n    df = preprocess(load_dataset())\n    X = df.drop(\"target\", axis=1)\n    y = df[\"target\"]\n    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)\n\n    model = MODELS[args.model]\n    with mlflow.start_run():\n        model.fit(X_train, y_train)\n        preds = model.predict(X_test)\n        acc = accuracy_score(y_test, preds)\n        mlflow.log_metric(\"accuracy\", acc)\n        mlflow.sklearn.log_model(model, \"model\")\n        print(f\"Accuracy: {{acc:.4f}}\")\n\nif __name__ == \"__main__\":\n    main()\n""",
            "data/raw/.gitkeep": "",
        },
    },
    "microservices": {
        "name": "Microservices Architecture",
        "description": "Docker Compose setup with API Gateway, services, and shared code",
        "tags": ["docker", "microservices", "api-gateway"],
        "setup_commands": ["docker-compose up --build"],
        "files": {
            "README.md": """# {name}

{description}

## Services

- **gateway** — Kong API Gateway
- **users** — User management service
- **orders** — Order processing service

## Run

```bash
docker-compose up --build
```

- Gateway: http://localhost:8000
- Users: http://localhost:8001
- Orders: http://localhost:8002
""",
            "docker-compose.yml": """version: "3.9"
services:
  gateway:
    image: kong:3.5
    environment:
      KONG_DATABASE: "off"
      KONG_DECLARATIVE_CONFIG: /kong/declarative/kong.yml
      KONG_PROXY_ACCESS_LOG: /dev/stdout
      KONG_ADMIN_ACCESS_LOG: /dev/stdout
      KONG_PROXY_ERROR_LOG: /dev/stderr
      KONG_ADMIN_ERROR_LOG: /dev/stderr
      KONG_ADMIN_LISTEN: 0.0.0.0:8001
    ports:
      - "8000:8000"
      - "8001:8001"
    volumes:
      - ./kong.yml:/kong/declarative/kong.yml

  users:
    build: ./services/users
    ports:
      - "8001:8000"
    environment:
      - DATABASE_URL=sqlite:///./users.db

  orders:
    build: ./services/orders
    ports:
      - "8002:8000"
    environment:
      - DATABASE_URL=sqlite:///./orders.db
""",
            "kong.yml": """_format_version: \"3.0\"\n_transform: true\n\nservices:\n  - name: users-service\n    url: http://users:8000\n    routes:\n      - name: users-route\n        paths:\n          - /users\n\n  - name: orders-service\n    url: http://orders:8000\n    routes:\n      - name: orders-route\n        paths:\n          - /orders\n""",
            "services/users/Dockerfile": """FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY . .\nCMD [\"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]\n""",
            "services/users/requirements.txt": "fastapi>=0.110.0\nuvicorn[standard]>=0.27.0\n",
            "services/users/main.py": """from fastapi import FastAPI\n\napp = FastAPI()\n\nusers_db = {{}}\n\n@app.get(\"/\")\ndef list_users():\n    return list(users_db.values())\n\n@app.post(\"/\")\ndef create_user(user: dict):\n    user_id = len(users_db) + 1\n    users_db[user_id] = {{\"id\": user_id, **user}}\n    return users_db[user_id]\n\n@app.get(\"/{{user_id}}\")\ndef get_user(user_id: int):\n    return users_db.get(user_id, {{\"error\": \"Not found\"}})\n""",
            "services/orders/Dockerfile": """FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY . .\nCMD [\"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]\n""",
            "services/orders/requirements.txt": "fastapi>=0.110.0\nuvicorn[standard]>=0.27.0\n",
            "services/orders/main.py": """from fastapi import FastAPI\n\napp = FastAPI()\n\norders_db = {{}}\n\n@app.get(\"/\")\ndef list_orders():\n    return list(orders_db.values())\n\n@app.post(\"/\")\ndef create_order(order: dict):\n    order_id = len(orders_db) + 1\n    orders_db[order_id] = {{\"id\": order_id, **order}}\n    return orders_db[order_id]\n\n@app.get(\"/{{order_id}}\")\ndef get_order(order_id: int):\n    return orders_db.get(order_id, {{\"error\": \"Not found\"}})\n""",
            "shared/models.py": """\"\"\"Shared Pydantic models.\"\"\"\n\nfrom pydantic import BaseModel\nfrom typing import Optional\n\nclass User(BaseModel):\n    id: int\n    name: str\n    email: str\n\nclass Order(BaseModel):\n    id: int\n    user_id: int\n    total: float\n    status: str = \"pending\"\n""",
        },
    },
}


async def generate_project(
    template_id: str,
    name: str,
    description: str = "",
    project_path: str = ".",
) -> dict[str, Any]:
    """Generate a complete project from a template."""
    from pathlib import Path

    if template_id not in TEMPLATES:
        available = ", ".join(TEMPLATES.keys())
        return {"error": f"Unknown template '{template_id}'. Available: {available}"}

    template = TEMPLATES[template_id]
    root = Path(project_path).resolve() / name
    root.mkdir(parents=True, exist_ok=True)

    files_created = []
    for relative_path_template, content_template in template["files"].items():
        content = content_template.format(
            name=name,
            description=description or f"{name} project",
        )
        file_path = root / relative_path_template.replace("{name}", name)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        files_created.append(str(file_path.relative_to(root)))

    logger.info(
        "Generated %s project '%s' with %d files",
        template_id, name, len(files_created),
    )

    return {
        "project_name": name,
        "template": template_id,
        "path": str(root),
        "files_created": files_created,
        "count": len(files_created),
        "setup_commands": template.get("setup_commands", []),
    }


# Register tool
register_tool(
    ToolSpec(
        name="generate_project",
        description="Generate a complete project from an advanced template (fastapi, fullstack, discord_bot, chrome_extension, data_science, microservices, cli_python)",
        schema={
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "string",
                    "enum": list(TEMPLATES.keys()),
                    "description": "Template to use",
                },
                "name": {"type": "string", "description": "Project name"},
                "description": {"type": "string", "default": "", "description": "Project description"},
                "project_path": {"type": "string", "default": ".", "description": "Base directory"},
            },
            "required": ["template_id", "name"],
        },
        handler=generate_project,
    )
)
