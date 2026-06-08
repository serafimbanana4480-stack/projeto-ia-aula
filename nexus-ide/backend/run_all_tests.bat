@echo off
setlocal enabledelayedexpansion
set total_passed=0
set total_failed=0
set total_skipped=0

for %%D in (agents config contracts core integration knowledge llm middleware observability orchestrator sandbox tools) do (
    echo Running tests/%%D ...
    py -m pytest tests/%%D -q --tb=short > %%D_test.log 2>&1
    for /f "tokens=1,2,3 delims=," %%a in ('py -m pytest tests/%%D -q --tb=no 2^>^&1 ^| findstr /R "passed.*failed.*skipped"') do (
        echo   %%a
    )
)
