#!/bin/bash
# Pre-commit hook: blocks commits containing secrets, API keys, or tokens.
# Install: cp scripts/pre-commit-secret-scan.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit

RED='\033[0;31m'
NC='\033[0m'

# Patterns that should NEVER appear in committed code
PATTERNS=(
    'sk-[A-Za-z0-9]{16,}'           # LiteLLM/OpenAI API keys
    'sha256~[A-Za-z0-9]{20,}'       # OpenShift tokens
    'eyJ[A-Za-z0-9_-]{50,}'         # JWT tokens (base64-encoded)
    'password\s*[:=]\s*"[^${\"]+'   # Hardcoded passwords (not env vars)
    'PRIVATE KEY'                    # Private keys
    'BEGIN RSA'                      # RSA keys
    'BEGIN EC'                       # EC keys
)

FOUND=0
for pattern in "${PATTERNS[@]}"; do
    matches=$(git diff --cached --diff-filter=ACMR -U0 -- . ':!scripts/pre-commit-secret-scan.sh' | grep -E "^\+" | grep -v "^+++" | grep -cE "$pattern" 2>/dev/null)
    if [ "$matches" -gt 0 ]; then
        echo -e "${RED}BLOCKED: Found potential secret matching pattern: $pattern${NC}"
        git diff --cached --diff-filter=ACMR -U0 | grep -E "^\+" | grep -v "^+++" | grep -E "$pattern" | head -3
        echo ""
        FOUND=1
    fi
done

# Check for known key values (add your specific keys here)
KNOWN_KEYS=(
    'd6d3ad6e4a3b4c68876919f2ac588782'
    'e42626831e854fe0a1eeac160a87b4bd'
    '324e9e1cd6cb94ff9b51b25e2ae09af1'
    'sk-YgLaSn9ILTPxaUwdDbmpGQ'
    'deepfield2026x'
)

for key in "${KNOWN_KEYS[@]}"; do
    matches=$(git diff --cached --diff-filter=ACMR -- . ':!scripts/pre-commit-secret-scan.sh' | grep -c "$key" 2>/dev/null)
    if [ "$matches" -gt 0 ]; then
        echo -e "${RED}BLOCKED: Found known secret value: ${key:0:8}...${NC}"
        FOUND=1
    fi
done

if [ "$FOUND" -eq 1 ]; then
    echo -e "${RED}Commit rejected. Remove secrets and use environment variables or K8s Secrets instead.${NC}"
    exit 1
fi

exit 0
