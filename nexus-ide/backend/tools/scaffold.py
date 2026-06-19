"""Project scaffolding tool — create complete project structures from templates.

Enables agents to bootstrap entire projects with proper structure,
configuration, and boilerplate.
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend.persistence.db import propose_change
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

# Project templates
TEMPLATES: dict[str, dict[str, str]] = {
    "python": {
        "README.md": "# {name}\n\n{description}\n\n## Setup\n\n```bash\npython -m venv .venv\nsource .venv/bin/activate  # Windows: .venv\\Scripts\\activate\npip install -r requirements.txt\n```\n\n## Run\n\n```bash\npython -m {name}\n```\n",
        "requirements.txt": "",
        ".gitignore": "__pycache__/\n*.pyc\n.venv/\n.env\n*.egg-info/\ndist/\nbuild/\n.pytest_cache/\n.mypy_cache/\n",
        "pyproject.toml": '[build-system]\nrequires = ["setuptools>=68"]\nbuild-backend = "setuptools.build_meta"\n\n[project]\nname = "{name}"\nversion = "0.1.0"\ndescription = "{description}"\nrequires-python = ">=3.12"\n',
        "src/{name}/__init__.py": '"""{description}"""\n\n__version__ = "0.1.0"\n',
        "src/{name}/main.py": 'def main() -> None:\n    print("Hello from {name}!")\n\nif __name__ == "__main__":\n    main()\n',
        "tests/__init__.py": "",
        "tests/test_main.py": "from {name}.main import main\n\ndef test_main() -> None:\n    main()\n",
    },
    "typescript": {
        "README.md": "# {name}\n\n{description}\n\n## Setup\n\n```bash\nnpm install\n```\n\n## Build\n\n```bash\nnpm run build\n```\n\n## Run\n\n```bash\nnpm start\n```\n",
        "package.json": '{\n  "name": "{name}",\n  "version": "0.1.0",\n  "description": "{description}",\n  "main": "dist/index.js",\n  "scripts": {\n    "build": "tsc",\n    "start": "node dist/index.js",\n    "dev": "ts-node src/index.ts",\n    "test": "jest"\n  },\n  "devDependencies": {\n    "typescript": "^5.0.0",\n    "@types/node": "^20.0.0",\n    "ts-node": "^10.9.0",\n    "jest": "^29.0.0",\n    "@types/jest": "^29.0.0"\n  }\n}\n',
        ".gitignore": "node_modules/\ndist/\n.env\n*.log\ncoverage/\n",
        "tsconfig.json": '{\n  "compilerOptions": {\n    "target": "ES2022",\n    "module": "commonjs",\n    "lib": ["ES2022"],\n    "outDir": "./dist",\n    "rootDir": "./src",\n    "strict": true,\n    "esModuleInterop": true,\n    "skipLibCheck": true,\n    "forceConsistentCasingInFileNames": true,\n    "declaration": true,\n    "sourceMap": true\n  },\n  "include": ["src/**/*"],\n  "exclude": ["node_modules", "dist"]\n}\n',
        "src/index.ts": "console.log('Hello from {name}!');\n",
        "src/index.test.ts": "describe('{name}', () => {\n  it('should work', () => {\n    expect(true).toBe(true);\n  });\n});\n",
    },
    "nextjs": {
        "README.md": "# {name}\n\n{description}\n\n## Setup\n\n```bash\nnpm install\n```\n\n## Dev\n\n```bash\nnpm run dev\n```\n\n## Build\n\n```bash\nnpm run build\n```\n",
        "package.json": '{\n  "name": "{name}",\n  "version": "0.1.0",\n  "private": true,\n  "scripts": {\n    "dev": "next dev",\n    "build": "next build",\n    "start": "next start",\n    "lint": "next lint"\n  },\n  "dependencies": {\n    "next": "^15.0.0",\n    "react": "^19.0.0",\n    "react-dom": "^19.0.0"\n  },\n  "devDependencies": {\n    "typescript": "^5.0.0",\n    "@types/node": "^20.0.0",\n    "@types/react": "^19.0.0",\n    "@types/react-dom": "^19.0.0",\n    "tailwindcss": "^4.0.0"\n  }\n}\n',
        ".gitignore": "node_modules/\n.next/\nout/\n.env\n*.log\n",
        "next.config.ts": "import type { NextConfig } from 'next';\n\nconst nextConfig: NextConfig = {\n  /* config options here */\n};\n\nexport default nextConfig;\n",
        "app/layout.tsx": "export const metadata = {\n  title: '{name}',\n  description: '{description}',\n};\n\nexport default function RootLayout({\n  children,\n}: Readonly<{\n  children: React.ReactNode;\n}>) {\n  return (\n    <html lang=\"en\">\n      <body>{children}</body>\n    </html>\n  );\n}\n",
        "app/page.tsx": 'export default function Home() {\n  return (\n    <main className="flex min-h-screen flex-col items-center justify-between p-24">\n      <h1>Welcome to {name}</h1>\n    </main>\n  );\n}\n',
        "app/globals.css": '@import "tailwindcss";\n',
        "tsconfig.json": '{\n  "compilerOptions": {\n    "lib": ["dom", "dom.iterable", "esnext"],\n    "allowJs": true,\n    "skipLibCheck": true,\n    "strict": true,\n    "noEmit": true,\n    "esModuleInterop": true,\n    "module": "esnext",\n    "moduleResolution": "bundler",\n    "resolveJsonModule": true,\n    "isolatedModules": true,\n    "jsx": "preserve",\n    "incremental": true,\n    "plugins": [{\n      "name": "next"\n    }],\n    "paths": {\n      "@/*": ["./*"]\n    }\n  },\n  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],\n  "exclude": ["node_modules"]\n}\n',
    },
    "fastapi": {
        "README.md": "# {name}\n\n{description}\n\n## Setup\n\n```bash\npython -m venv .venv\nsource .venv/bin/activate\npip install -r requirements.txt\n```\n\n## Run\n\n```bash\nuvicorn src.main:app --reload\n```\n\n## Docker\n\n```bash\ndocker-compose up --build\n```\n",
        "requirements.txt": "fastapi>=0.115.0\nuvicorn[standard]>=0.32.0\npydantic>=2.9.0\npytest>=8.3.0\nhttpx>=0.27.0\n",
        ".gitignore": "__pycache__/\n*.pyc\n.venv/\n.env\ndist/\nbuild/\n.pytest_cache/\n.mypy_cache/\n",
        "Dockerfile": 'FROM python:3.12-slim\n\nWORKDIR /app\n\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\n\nCOPY . .\n\nEXPOSE 8000\n\nCMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]\n',
        "docker-compose.yml": "version: '3.8'\n\nservices:\n  app:\n    build: .\n    ports:\n      - \"8000:8000\"\n    environment:\n      - DEBUG=true\n    volumes:\n      - .:/app\n",
        "src/__init__.py": "",
        "src/main.py": 'from fastapi import FastAPI\nfrom src.config import settings\nfrom src.models import Item\n\napp = FastAPI(title=settings.app_name, debug=settings.debug)\n\n\n@app.get("/")\nasync def root() -> dict:\n    return {"message": "Welcome to {name}"}\n\n\n@app.get("/health")\nasync def health() -> dict:\n    return {"status": "ok"}\n\n\n@app.post("/items")\nasync def create_item(item: Item) -> Item:\n    return item\n\n\n@app.get("/items/{item_id}")\nasync def read_item(item_id: int, q: str | None = None) -> dict:\n    return {"item_id": item_id, "q": q}\n',
        "src/config.py": 'from pydantic_settings import BaseSettings\n\n\nclass Settings(BaseSettings):\n    app_name: str = "{name}"\n    debug: bool = True\n    database_url: str = "sqlite:///./app.db"\n\n    class Config:\n        env_file = ".env"\n\n\nsettings = Settings()\n',
        "src/models.py": "from pydantic import BaseModel\n\n\nclass Item(BaseModel):\n    id: int\n    name: str\n    description: str | None = None\n    price: float\n    tax: float | None = None\n",
        "tests/__init__.py": "",
        "tests/test_main.py": 'import pytest\nfrom httpx import AsyncClient\nfrom src.main import app\n\n\n@pytest.fixture\nasync def client():\n    async with AsyncClient(app=app, base_url="http://test") as ac:\n        yield ac\n\n\n@pytest.mark.anyio\nasync def test_root(client: AsyncClient) -> None:\n    response = await client.get("/")\n    assert response.status_code == 200\n    assert "message" in response.json()\n\n\n@pytest.mark.anyio\nasync def test_health(client: AsyncClient) -> None:\n    response = await client.get("/health")\n    assert response.status_code == 200\n    assert response.json()["status"] == "ok"\n\n\n@pytest.mark.anyio\nasync def test_create_item(client: AsyncClient) -> None:\n    payload = {"id": 1, "name": "test", "price": 10.5}\n    response = await client.post("/items", json=payload)\n    assert response.status_code == 200\n    assert response.json()["name"] == "test"\n',
    },
    "django": {
        "README.md": "# {name}\n\n{description}\n\n## Setup\n\n```bash\npython -m venv .venv\nsource .venv/bin/activate\npip install -r requirements.txt\npython manage.py migrate\n```\n\n## Run\n\n```bash\npython manage.py runserver\n```\n",
        "requirements.txt": "Django>=5.1.0\ndjangorestframework>=3.15.0\npytest-django>=4.9.0\n",
        ".gitignore": "__pycache__/\n*.pyc\n.venv/\n.env\ndb.sqlite3\nmedia/\nstaticfiles/\n.pytest_cache/\n",
        "manage.py": '#!/usr/bin/env python\n"""Django management script."""\nimport os\nimport sys\n\nif __name__ == "__main__":\n    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "{name}.settings")\n    from django.core.management import execute_from_command_line\n    execute_from_command_line(sys.argv)\n',
        "{name}/__init__.py": "",
        "{name}/settings.py": 'from pathlib import Path\n\nBASE_DIR = Path(__file__).resolve().parent.parent\n\nSECRET_KEY = "django-insecure-change-me-in-production"\n\nDEBUG = True\n\nALLOWED_HOSTS = ["*"]\n\nINSTALLED_APPS = [\n    "django.contrib.admin",\n    "django.contrib.auth",\n    "django.contrib.contenttypes",\n    "django.contrib.sessions",\n    "django.contrib.messages",\n    "django.contrib.staticfiles",\n    "rest_framework",\n    "{name}.core",\n]\n\nMIDDLEWARE = [\n    "django.middleware.security.SecurityMiddleware",\n    "django.contrib.sessions.middleware.SessionMiddleware",\n    "django.middleware.common.CommonMiddleware",\n    "django.middleware.csrf.CsrfViewMiddleware",\n    "django.contrib.auth.middleware.AuthenticationMiddleware",\n    "django.contrib.messages.middleware.MessageMiddleware",\n    "django.middleware.clickjacking.XFrameOptionsMiddleware",\n]\n\nROOT_URLCONF = "{name}.urls"\n\nTEMPLATES = [\n    {\n        "BACKEND": "django.template.backends.django.DjangoTemplates",\n        "DIRS": [BASE_DIR / "templates"],\n        "APP_DIRS": True,\n        "OPTIONS": {\n            "context_processors": [\n                "django.template.context_processors.debug",\n                "django.template.context_processors.request",\n                "django.contrib.auth.context_processors.auth",\n                "django.contrib.messages.context_processors.messages",\n            ],\n        },\n    },\n]\n\nWSGI_APPLICATION = "{name}.wsgi.application"\n\nDATABASES = {\n    "default": {\n        "ENGINE": "django.db.backends.sqlite3",\n        "NAME": BASE_DIR / "db.sqlite3",\n    }\n}\n\nLANGUAGE_CODE = "en-us"\nTIME_ZONE = "UTC"\nUSE_I18N = True\nUSE_TZ = True\n\nSTATIC_URL = "static/"\n\nDEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"\n',
        "{name}/urls.py": 'from django.contrib import admin\nfrom django.urls import path, include\n\nurlpatterns = [\n    path("admin/", admin.site.urls),\n    path("api/", include("{name}.core.urls")),\n]\n',
        "{name}/wsgi.py": 'import os\nfrom django.core.wsgi import get_wsgi_application\nos.environ.setdefault("DJANGO_SETTINGS_MODULE", "{name}.settings")\napplication = get_wsgi_application()\n',
        "{name}/core/__init__.py": "",
        "{name}/core/models.py": "from django.db import models\n\n\nclass Task(models.Model):\n    title = models.CharField(max_length=200)\n    description = models.TextField(blank=True)\n    completed = models.BooleanField(default=False)\n    created_at = models.DateTimeField(auto_now_add=True)\n\n    def __str__(self) -> str:\n        return self.title\n",
        "{name}/core/views.py": 'from django.http import JsonResponse\nfrom django.views import View\nfrom {name}.core.models import Task\n\n\nclass TaskListView(View):\n    def get(self, request):\n        tasks = Task.objects.all().values()\n        return JsonResponse({"tasks": list(tasks)})\n',
        "{name}/core/urls.py": 'from django.urls import path\nfrom {name}.core.views import TaskListView\n\nurlpatterns = [\n    path("tasks/", TaskListView.as_view(), name="task-list"),\n]\n',
        "{name}/core/admin.py": "from django.contrib import admin\nfrom {name}.core.models import Task\n\nadmin.site.register(Task)\n",
        "tests/__init__.py": "",
        "tests/test_models.py": 'import pytest\nfrom {name}.core.models import Task\n\n\n@pytest.mark.django_db\ndef test_task_creation() -> None:\n    task = Task.objects.create(title="Test Task")\n    assert task.title == "Test Task"\n    assert task.completed is False\n',
    },
    "react": {
        "README.md": "# {name}\n\n{description}\n\n## Setup\n\n```bash\nnpm install\n```\n\n## Dev\n\n```bash\nnpm run dev\n```\n\n## Build\n\n```bash\nnpm run build\n```\n",
        "package.json": '{\n  "name": "{name}",\n  "version": "0.1.0",\n  "private": true,\n  "type": "module",\n  "scripts": {\n    "dev": "vite",\n    "build": "tsc && vite build",\n    "preview": "vite preview",\n    "test": "vitest"\n  },\n  "dependencies": {\n    "react": "^19.0.0",\n    "react-dom": "^19.0.0",\n    "react-router-dom": "^7.0.0"\n  },\n  "devDependencies": {\n    "@types/react": "^19.0.0",\n    "@types/react-dom": "^19.0.0",\n    "@vitejs/plugin-react": "^4.3.0",\n    "typescript": "^5.6.0",\n    "vite": "^6.0.0",\n    "vitest": "^2.1.0"\n  }\n}\n',
        ".gitignore": "node_modules/\ndist/\n.env\n*.log\n",
        "vite.config.ts": 'import { defineConfig } from "vite";\nimport react from "@vitejs/plugin-react";\n\nexport default defineConfig({\n  plugins: [react()],\n});\n',
        "tsconfig.json": '{\n  "compilerOptions": {\n    "target": "ES2020",\n    "useDefineForClassFields": true,\n    "lib": ["ES2020", "DOM", "DOM.Iterable"],\n    "module": "ESNext",\n    "skipLibCheck": true,\n    "moduleResolution": "bundler",\n    "allowImportingTsExtensions": true,\n    "isolatedModules": true,\n    "moduleDetection": "force",\n    "noEmit": true,\n    "jsx": "react-jsx",\n    "strict": true,\n    "noUnusedLocals": true,\n    "noUnusedParameters": true,\n    "noFallthroughCasesInSwitch": true\n  },\n  "include": ["src"]\n}\n',
        "index.html": '<!doctype html>\n<html lang="en">\n  <head>\n    <meta charset="UTF-8" />\n    <link rel="icon" type="image/svg+xml" href="/vite.svg" />\n    <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n    <title>{name}</title>\n  </head>\n  <body>\n    <div id="root"></div>\n    <script type="module" src="/src/main.tsx"></script>\n  </body>\n</html>\n',
        "src/main.tsx": 'import { StrictMode } from "react";\nimport { createRoot } from "react-dom/client";\nimport { BrowserRouter } from "react-router-dom";\nimport App from "./App";\n\ncreateRoot(document.getElementById("root")!).render(\n  <StrictMode>\n    <BrowserRouter>\n      <App />\n    </BrowserRouter>\n  </StrictMode>\n);\n',
        "src/App.tsx": 'import { Routes, Route } from "react-router-dom";\nimport { Home } from "./components/Home";\n\nfunction App() {\n  return (\n    <div className="app">\n      <header>\n        <h1>{name}</h1>\n      </header>\n      <Routes>\n        <Route path="/" element={<Home />} />\n      </Routes>\n    </div>\n  );\n}\n\nexport default App;\n',
        "src/components/Home.tsx": "export function Home() {\n  return (\n    <section>\n      <h2>Home</h2>\n      <p>Welcome to {name}!</p>\n    </section>\n  );\n}\n",
        "src/hooks/useCounter.ts": 'import { useState } from "react";\n\nexport function useCounter(initial = 0) {\n  const [count, setCount] = useState(initial);\n  const increment = () => setCount((c) => c + 1);\n  const decrement = () => setCount((c) => c - 1);\n  const reset = () => setCount(initial);\n  return { count, increment, decrement, reset };\n}\n',
    },
    "vue": {
        "README.md": "# {name}\n\n{description}\n\n## Setup\n\n```bash\nnpm install\n```\n\n## Dev\n\n```bash\nnpm run dev\n```\n\n## Build\n\n```bash\nnpm run build\n```\n",
        "package.json": '{\n  "name": "{name}",\n  "version": "0.1.0",\n  "private": true,\n  "type": "module",\n  "scripts": {\n    "dev": "vite",\n    "build": "vue-tsc && vite build",\n    "preview": "vite preview",\n    "test": "vitest"\n  },\n  "dependencies": {\n    "vue": "^3.5.0",\n    "vue-router": "^4.4.0"\n  },\n  "devDependencies": {\n    "@vitejs/plugin-vue": "^5.1.0",\n    "typescript": "^5.6.0",\n    "vite": "^6.0.0",\n    "vue-tsc": "^2.1.0",\n    "vitest": "^2.1.0"\n  }\n}\n',
        ".gitignore": "node_modules/\ndist/\n.env\n*.log\n",
        "vite.config.ts": 'import { defineConfig } from "vite";\nimport vue from "@vitejs/plugin-vue";\n\nexport default defineConfig({\n  plugins: [vue()],\n});\n',
        "tsconfig.json": '{\n  "compilerOptions": {\n    "target": "ES2020",\n    "useDefineForClassFields": true,\n    "module": "ESNext",\n    "lib": ["ES2020", "DOM", "DOM.Iterable"],\n    "skipLibCheck": true,\n    "moduleResolution": "bundler",\n    "allowImportingTsExtensions": true,\n    "isolatedModules": true,\n    "moduleDetection": "force",\n    "noEmit": true,\n    "jsx": "preserve",\n    "strict": true,\n    "noUnusedLocals": true,\n    "noUnusedParameters": true,\n    "noFallthroughCasesInSwitch": true\n  },\n  "include": ["src/**/*.ts", "src/**/*.tsx", "src/**/*.vue"]\n}\n',
        "index.html": '<!doctype html>\n<html lang="en">\n  <head>\n    <meta charset="UTF-8" />\n    <link rel="icon" type="image/svg+xml" href="/vite.svg" />\n    <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n    <title>{name}</title>\n  </head>\n  <body>\n    <div id="app"></div>\n    <script type="module" src="/src/main.ts"></script>\n  </body>\n</html>\n',
        "src/main.ts": 'import { createApp } from "vue";\nimport App from "./App.vue";\nimport router from "./router";\n\nconst app = createApp(App);\napp.use(router);\napp.mount("#app");\n',
        "src/App.vue": '<script setup lang="ts">\nimport { RouterView } from "vue-router";\n</script>\n\n<template>\n  <div id="app">\n    <header>\n      <h1>{name}</h1>\n    </header>\n    <RouterView />\n  </div>\n</template>\n\n<style scoped>\nh1 {\n  color: #42b883;\n}\n</style>\n',
        "src/router/index.ts": 'import { createRouter, createWebHistory } from "vue-router";\nimport Home from "../components/Home.vue";\n\nconst routes = [\n  { path: "/", component: Home },\n];\n\nconst router = createRouter({\n  history: createWebHistory(),\n  routes,\n});\n\nexport default router;\n',
        "src/components/Home.vue": '<script setup lang="ts">\nimport { ref } from "vue";\n\nconst count = ref(0);\n</script>\n\n<template>\n  <section>\n    <h2>Home</h2>\n    <p>Welcome to {name}!</p>\n    <button @click="count++">Count is {{ count }}</button>\n  </section>\n</template>\n',
    },
    "rust": {
        "README.md": "# {name}\n\n{description}\n\n## Setup\n\n```bash\nrustup update\n```\n\n## Build\n\n```bash\ncargo build --release\n```\n\n## Run\n\n```bash\ncargo run\n```\n\n## Test\n\n```bash\ncargo test\n```\n",
        "Cargo.toml": '[package]\nname = "{name}"\nversion = "0.1.0"\nedition = "2021"\n\n[dependencies]\nserde = { version = "1.0", features = ["derive"] }\ntokio = { version = "1.40", features = ["full"] }\naxum = "0.7"\nanyhow = "1.0"\n\n[dev-dependencies]\nassert_fs = "1.1"\npredicates = "3.1"\n',
        ".gitignore": "/target\nCargo.lock\n*.rs.bk\n",
        "src/main.rs": 'use anyhow::Result;\nuse axum::{routing::get, Router};\n\n#[tokio::main]\nasync fn main() -> Result<()> {\n    let app = Router::new().route("/", get(handlers::root));\n    let listener = tokio::net::TcpListener::bind("0.0.0.0:3000").await?;\n    println!("Listening on http://0.0.0.0:3000");\n    axum::serve(listener, app).await?;\n    Ok(())\n}\n',
        "src/lib.rs": "pub mod config;\npub mod handlers;\n\npub fn add(left: u64, right: u64) -> u64 {\n    left + right\n}\n\n#[cfg(test)]\nmod tests {\n    use super::*;\n\n    #[test]\n    fn test_add() {\n        assert_eq!(add(2, 2), 4);\n    }\n}\n",
        "src/config.rs": 'pub struct Config {\n    pub port: u16,\n    pub host: String,\n}\n\nimpl Config {\n    pub fn from_env() -> Self {\n        Self {\n            port: std::env::var("PORT")\n                .ok()\n                .and_then(|p| p.parse().ok())\n                .unwrap_or(3000),\n            host: std::env::var("HOST").unwrap_or_else(|_| "0.0.0.0".to_string()),\n        }\n    }\n}\n',
        "src/handlers.rs": 'use axum::response::Json;\nuse serde_json::json;\n\npub async fn root() -> Json<serde_json::Value> {\n    Json(json!({"message": "Welcome to {name}"}))\n}\n',
        "tests/integration_test.rs": "use {name}::add;\n\n#[test]\nfn test_add_integration() {\n    assert_eq!(add(3, 4), 7);\n}\n",
        "Dockerfile": 'FROM rust:1.82-slim AS builder\nWORKDIR /app\nCOPY Cargo.toml Cargo.lock ./\nCOPY src ./src\nRUN cargo build --release\n\nFROM debian:bookworm-slim\nWORKDIR /app\nCOPY --from=builder /app/target/release/{name} ./app\nEXPOSE 3000\nCMD ["./app"]\n',
    },
    "go": {
        "README.md": "# {name}\n\n{description}\n\n## Setup\n\n```bash\ngo mod tidy\n```\n\n## Build\n\n```bash\ngo build -o bin/{name} ./cmd/{name}\n```\n\n## Run\n\n```bash\ngo run ./cmd/{name}\n```\n\n## Test\n\n```bash\ngo test ./...\n```\n",
        "go.mod": "module github.com/example/{name}\n\ngo 1.23\n",
        ".gitignore": "bin/\n*.exe\n*.dll\n*.so\n*.dylib\n*.test\n*.out\nvendor/\n",
        "cmd/{name}/main.go": 'package main\n\nimport (\n\t"fmt"\n\t"github.com/example/{name}/internal/greeting"\n)\n\nfunc main() {\n\tfmt.Println(greeting.Hello("{name}"))\n}\n',
        "internal/greeting/greeting.go": 'package greeting\n\nimport "fmt"\n\nfunc Hello(name string) string {\n\treturn fmt.Sprintf("Hello, %s!", name)\n}\n',
        "internal/greeting/greeting_test.go": 'package greeting\n\nimport "testing"\n\nfunc TestHello(t *testing.T) {\n\tgot := Hello("World")\n\twant := "Hello, World!"\n\tif got != want {\n\t\tt.Errorf("Hello() = %q, want %q", got, want)\n\t}\n}\n',
        "pkg/utils/utils.go": "package utils\n\nfunc Reverse(s string) string {\n\trunes := []rune(s)\n\tfor i, j := 0, len(runes)-1; i < j; i, j = i+1, j-1 {\n\t\trunes[i], runes[j] = runes[j], runes[i]\n\t}\n\treturn string(runes)\n}\n",
        "pkg/utils/utils_test.go": 'package utils\n\nimport "testing"\n\nfunc TestReverse(t *testing.T) {\n\tgot := Reverse("hello")\n\twant := "olleh"\n\tif got != want {\n\t\tt.Errorf("Reverse() = %q, want %q", got, want)\n\t}\n}\n',
        "Dockerfile": 'FROM golang:1.23-alpine AS builder\nWORKDIR /app\nCOPY go.mod go.sum ./\nRUN go mod download\nCOPY . .\nRUN go build -o /app/bin/{name} ./cmd/{name}\n\nFROM alpine:latest\nRUN apk --no-cache add ca-certificates\nWORKDIR /root/\nCOPY --from=builder /app/bin/{name} .\nCMD ["./{name}"]\n',
    },
    "flutter": {
        "README.md": "# {name}\n\n{description}\n\n## Setup\n\n```bash\nflutter pub get\n```\n\n## Run\n\n```bash\nflutter run\n```\n\n## Test\n\n```bash\nflutter test\n```\n",
        "pubspec.yaml": "name: {name}\ndescription: {description}\npublish_to: 'none'\nversion: 1.0.0+1\n\nenvironment:\n  sdk: '>=3.5.0 <4.0.0'\n\ndependencies:\n  flutter:\n    sdk: flutter\n  http: ^1.2.0\n\ndev_dependencies:\n  flutter_test:\n    sdk: flutter\n  flutter_lints: ^5.0.0\n\nflutter:\n  uses-material-design: true\n",
        ".gitignore": "/build/\n/.dart_tool/\n/.idea/\n/.vscode/\n*.iml\n*.log\n",
        "lib/main.dart": 'import "package:flutter/material.dart";\nimport "package:{name}/screens/home_screen.dart";\n\nvoid main() {\n  runApp(const MyApp());\n}\n\nclass MyApp extends StatelessWidget {\n  const MyApp({super.key});\n\n  @override\n  Widget build(BuildContext context) {\n    return MaterialApp(\n      title: "{name}",\n      theme: ThemeData(\n        colorScheme: ColorScheme.fromSeed(seedColor: Colors.deepPurple),\n        useMaterial3: true,\n      ),\n      home: const HomeScreen(),\n    );\n  }\n}\n',
        "lib/screens/home_screen.dart": 'import "package:flutter/material.dart";\nimport "package:{name}/widgets/counter_button.dart";\n\nclass HomeScreen extends StatefulWidget {\n  const HomeScreen({super.key});\n\n  @override\n  State<HomeScreen> createState() => _HomeScreenState();\n}\n\nclass _HomeScreenState extends State<HomeScreen> {\n  int _counter = 0;\n\n  void _increment() {\n    setState(() {\n      _counter++;\n    });\n  }\n\n  @override\n  Widget build(BuildContext context) {\n    return Scaffold(\n      appBar: AppBar(\n        title: const Text("{name}"),\n      ),\n      body: Center(\n        child: Column(\n          mainAxisAlignment: MainAxisAlignment.center,\n          children: [\n            const Text("You have pushed the button this many times:"),\n            Text(\n              "$_counter",\n              style: Theme.of(context).textTheme.headlineMedium,\n            ),\n            CounterButton(onPressed: _increment),\n          ],\n        ),\n      ),\n    );\n  }\n}\n',
        "lib/widgets/counter_button.dart": 'import "package:flutter/material.dart";\n\nclass CounterButton extends StatelessWidget {\n  final VoidCallback onPressed;\n\n  const CounterButton({super.key, required this.onPressed});\n\n  @override\n  Widget build(BuildContext context) {\n    return FloatingActionButton(\n      onPressed: onPressed,\n      tooltip: "Increment",\n      child: const Icon(Icons.add),\n    );\n  }\n}\n',
        "lib/models/counter_model.dart": "class CounterModel {\n  int value;\n\n  CounterModel({this.value = 0});\n\n  void increment() => value++;\n\n  void decrement() => value--;\n}\n",
        "test/widget_test.dart": 'import "package:flutter/material.dart";\nimport "package:flutter_test/flutter_test.dart";\nimport "package:{name}/main.dart";\n\nvoid main() {\n  testWidgets("Counter increments smoke test", (WidgetTester tester) async {\n    await tester.pumpWidget(const MyApp());\n    expect(find.text("0"), findsOneWidget);\n    await tester.tap(find.byType(FloatingActionButton));\n    await tester.pump();\n    expect(find.text("1"), findsOneWidget);\n  });\n}\n',
    },
    "data_science": {
        "README.md": "# {name}\n\n{description}\n\n## Setup\n\n```bash\npython -m venv .venv\nsource .venv/bin/activate\npip install -r requirements.txt\n```\n\n## Notebooks\n\n```bash\njupyter notebook notebooks/\n```\n\n## Train\n\n```bash\npython src/train.py\n```\n",
        "requirements.txt": "jupyter>=1.1.0\nnumpy>=2.1.0\npandas>=2.2.0\nscikit-learn>=1.5.0\nmatplotlib>=3.9.0\nseaborn>=0.13.0\npyyaml>=6.0.0\n",
        ".gitignore": "__pycache__/\n*.pyc\n.venv/\n.env\ndata/raw/\ndata/processed/\nmodels/\nnotebooks/.ipynb_checkpoints/\n.pytest_cache/\n",
        "config.yaml": "project:\n  name: {name}\n  version: 0.1.0\n\ndata:\n  raw_path: data/raw\n  processed_path: data/processed\n\nmodel:\n  type: random_forest\n  params:\n    n_estimators: 100\n    max_depth: 10\n\ntraining:\n  test_size: 0.2\n  random_state: 42\n",
        "notebooks/exploration.ipynb": '{\n "cells": [\n  {\n   "cell_type": "markdown",\n   "metadata": {},\n   "source": [\n    "# {name} - Data Exploration"\n   ]\n  },\n  {\n   "cell_type": "code",\n   "execution_count": null,\n   "metadata": {},\n   "outputs": [],\n   "source": [\n    "import pandas as pd\\n",\n    "import matplotlib.pyplot as plt\\n",\n    "import seaborn as sns"\n   ]\n  },\n  {\n   "cell_type": "code",\n   "execution_count": null,\n   "metadata": {},\n   "outputs": [],\n   "source": [\n    "# Load data\\n",\n    "df = pd.read_csv(\\"data/raw/sample.csv\\")\\n",\n    "df.head()"\n   ]\n  }\n ],\n "metadata": {\n  "kernelspec": {\n   "display_name": "Python 3",\n   "language": "python",\n   "name": "python3"\n  },\n  "language_info": {\n   "name": "python",\n   "version": "3.12.0"\n  }\n },\n "nbformat": 4,\n "nbformat_minor": 4\n}\n',
        "src/__init__.py": "",
        "src/data.py": 'import pandas as pd\nfrom pathlib import Path\n\n\ndef load_data(path: str) -> pd.DataFrame:\n    """Load CSV data from the given path."""\n    return pd.read_csv(path)\n\n\ndef preprocess(df: pd.DataFrame) -> pd.DataFrame:\n    """Basic preprocessing: drop NA and duplicates."""\n    df = df.dropna()\n    df = df.drop_duplicates()\n    return df\n\n\ndef split_features_target(df: pd.DataFrame, target_column: str):\n    """Split DataFrame into features and target."""\n    X = df.drop(columns=[target_column])\n    y = df[target_column]\n    return X, y\n',
        "src/models.py": 'from sklearn.ensemble import RandomForestClassifier\nfrom sklearn.linear_model import LogisticRegression\nfrom typing import Any\n\n\ndef get_model(model_type: str = "random_forest", **kwargs: Any):\n    """Factory to return a model instance."""\n    if model_type == "random_forest":\n        return RandomForestClassifier(**kwargs)\n    elif model_type == "logistic_regression":\n        return LogisticRegression(max_iter=1000, **kwargs)\n    else:\n        raise ValueError(f"Unknown model type: {model_type}")\n',
        "src/train.py": 'import yaml\nfrom pathlib import Path\nfrom sklearn.model_selection import train_test_split\nfrom sklearn.metrics import accuracy_score\n\nfrom src.data import load_data, preprocess, split_features_target\nfrom src.models import get_model\n\n\ndef main() -> None:\n    config_path = Path("config.yaml")\n    with config_path.open("r") as f:\n        config = yaml.safe_load(f)\n\n    raw_path = Path(config["data"]["raw_path"]) / "sample.csv"\n    df = load_data(str(raw_path))\n    df = preprocess(df)\n\n    X, y = split_features_target(df, target_column="target")\n    X_train, X_test, y_train, y_test = train_test_split(\n        X, y, test_size=config["training"]["test_size"], random_state=config["training"]["random_state"]\n    )\n\n    model = get_model(\n        config["model"]["type"], **config["model"]["params"]\n    )\n    model.fit(X_train, y_train)\n\n    y_pred = model.predict(X_test)\n    acc = accuracy_score(y_test, y_pred)\n    print(f"Accuracy: {acc:.4f}")\n\n\nif __name__ == "__main__":\n    main()\n',
        "tests/__init__.py": "",
        "tests/test_data.py": 'import pandas as pd\nfrom src.data import preprocess, split_features_target\n\n\ndef test_preprocess() -> None:\n    df = pd.DataFrame({"a": [1, 2, None], "b": [4, 5, 6]})\n    result = preprocess(df)\n    assert len(result) == 2\n\n\ndef test_split_features_target() -> None:\n    df = pd.DataFrame({"a": [1, 2], "target": [0, 1]})\n    X, y = split_features_target(df, "target")\n    assert list(X.columns) == ["a"]\n    assert list(y) == [0, 1]\n',
        "Dockerfile": 'FROM python:3.12-slim\n\nWORKDIR /app\n\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\n\nCOPY . .\n\nCMD ["python", "src/train.py"]\n',
    },
    "microservices": {
        "README.md": "# {name}\n\n{description}\n\n## Setup\n\n```bash\ncp .env.example .env\ndocker-compose up --build\n```\n\n## Services\n\n- `api-gateway` — Kong API Gateway\n- `user-service` — User management\n- `order-service` — Order processing\n",
        ".env.example": "# Database\nPOSTGRES_USER=admin\nPOSTGRES_PASSWORD=changeme\nPOSTGRES_DB={name}\n\n# Kong\nKONG_DATABASE=postgres\n\n# Services\nUSER_SERVICE_PORT=8001\nORDER_SERVICE_PORT=8002\n",
        ".gitignore": ".env\n__pycache__/\n*.pyc\n.venv/\nnode_modules/\n",
        "docker-compose.yml": 'version: \'3.8\'\n\nservices:\n  kong-db:\n    image: postgres:16-alpine\n    environment:\n      POSTGRES_USER: ${POSTGRES_USER}\n      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}\n      POSTGRES_DB: ${POSTGRES_DB}\n    volumes:\n      - kong-db-data:/var/lib/postgresql/data\n\n  kong:\n    image: kong:3.7\n    environment:\n      KONG_DATABASE: ${KONG_DATABASE}\n      KONG_PG_HOST: kong-db\n      KONG_PG_USER: ${POSTGRES_USER}\n      KONG_PG_PASSWORD: ${POSTGRES_PASSWORD}\n      KONG_CASSANDRA_CONTACT_POINTS: kong-db\n      KONG_PROXY_ACCESS_LOG: /dev/stdout\n      KONG_ADMIN_ACCESS_LOG: /dev/stdout\n      KONG_PROXY_ERROR_LOG: /dev/stderr\n      KONG_ADMIN_ERROR_LOG: /dev/stderr\n    ports:\n      - "8000:8000"\n      - "8443:8443"\n      - "8001:8001"\n      - "8444:8444"\n    depends_on:\n      - kong-db\n\n  user-service:\n    build: ./services/user-service\n    ports:\n      - "${USER_SERVICE_PORT}:8000"\n    environment:\n      - PORT=8000\n\n  order-service:\n    build: ./services/order-service\n    ports:\n      - "${ORDER_SERVICE_PORT}:8000"\n    environment:\n      - PORT=8000\n\nvolumes:\n  kong-db-data:\n',
        "kong.yml": '_format_version: "3.0"\n\nservices:\n  - name: user-service\n    url: http://user-service:8000\n    routes:\n      - name: user-routes\n        paths:\n          - /users\n\n  - name: order-service\n    url: http://order-service:8000\n    routes:\n      - name: order-routes\n        paths:\n          - /orders\n\nplugins:\n  - name: rate-limiting\n    config:\n      minute: 100\n',
        "services/user-service/Dockerfile": 'FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY . .\nEXPOSE 8000\nCMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]\n',
        "services/user-service/requirements.txt": "fastapi>=0.115.0\nuvicorn[standard]>=0.32.0\n",
        "services/user-service/main.py": 'from fastapi import FastAPI\n\napp = FastAPI()\n\nusers = []\n\n@app.get("/users")\nasync def list_users():\n    return users\n\n@app.post("/users")\nasync def create_user(user: dict):\n    users.append(user)\n    return user\n',
        "services/order-service/Dockerfile": 'FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY . .\nEXPOSE 8000\nCMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]\n',
        "services/order-service/requirements.txt": "fastapi>=0.115.0\nuvicorn[standard]>=0.32.0\n",
        "services/order-service/main.py": 'from fastapi import FastAPI\n\napp = FastAPI()\n\norders = []\n\n@app.get("/orders")\nasync def list_orders():\n    return orders\n\n@app.post("/orders")\nasync def create_order(order: dict):\n    orders.append(order)\n    return order\n',
        "shared/__init__.py": "",
        "shared/schemas.py": "from pydantic import BaseModel\nfrom typing import Optional\nfrom datetime import datetime\n\n\nclass User(BaseModel):\n    id: int\n    username: str\n    email: str\n    created_at: Optional[datetime] = None\n\n\nclass Order(BaseModel):\n    id: int\n    user_id: int\n    total: float\n    status: str\n    created_at: Optional[datetime] = None\n",
        "Makefile": ".PHONY: up down logs\n\nup:\n\tdocker-compose up --build -d\n\ndown:\n\tdocker-compose down -v\n\nlogs:\n\tdocker-compose logs -f\n",
    },
}


async def scaffold_project(
    name: str,
    template: str = "python",
    project_path: str = ".",
    description: str = "",
    session_id: str | None = None,
) -> dict:
    """Create a complete project structure from a template."""
    try:
        if template not in TEMPLATES:
            available = ", ".join(TEMPLATES.keys())
            return {"error": f"Unknown template '{template}'. Available: {available}"}

        root = Path(project_path).resolve() / name
        root.mkdir(parents=True, exist_ok=True)

        files_created = []
        template_files = TEMPLATES[template]

        for relative_path, content_template in template_files.items():
            content = content_template.replace("{name}", name).replace(
                "{description}", description or f"{name} project"
            )
            file_path = root / relative_path.replace("{name}", name)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            files_created.append(str(file_path.relative_to(root)))

            if session_id:
                propose_change(
                    session_id=session_id,
                    file_path=str(file_path),
                    operation="create",
                    new_content=content,
                )

        logger.info("Scaffolded %s project '%s' with %d files", template, name, len(files_created))
        return {
            "project_name": name,
            "template": template,
            "path": str(root),
            "files_created": files_created,
            "count": len(files_created),
        }
    except Exception as e:
        return {"error": f"Scaffold failed: {e}"}


# Register tool
register_tool(
    ToolSpec(
        name="scaffold_project",
        description="Create a complete project structure from a template",
        schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name"},
                "template": {
                    "type": "string",
                    "enum": list(TEMPLATES.keys()),
                    "default": "python",
                    "description": "Project template",
                },
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Base directory",
                },
                "description": {
                    "type": "string",
                    "default": "",
                    "description": "Project description",
                },
            },
            "required": ["name"],
        },
        handler=scaffold_project,
    )
)
