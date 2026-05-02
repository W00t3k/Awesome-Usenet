#!/bin/bash

# Majic Movie Selector - Fully Automated Setup Script
# Sets up virtual environment, installs dependencies, and configures .env

set -e

echo "🎬 Majic Movie Selector Setup"
echo "=============================="

# Function to get user input with default
get_input() {
    local prompt="$1"
    local default="$2"
    local var_name="$3"
    
    echo -n "$prompt [$default]: "
    read -r response
    if [[ -z "$response" ]]; then
        response="$default"
    fi
    eval "$var_name='$response'"
}

# Check if Python 3.11+ is available
python_cmd=""
if command -v python3.12 &> /dev/null; then
    python_cmd="python3.12"
elif command -v python3.11 &> /dev/null; then
    python_cmd="python3.11"
elif command -v python3 &> /dev/null; then
    python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    if [[ $(echo "$python_version >= 3.11" | bc -l 2>/dev/null || echo "1") -eq 1 ]]; then
        python_cmd="python3"
    else
        echo "❌ Python 3.11+ required. Found: $python_version"
        exit 1
    fi
else
    echo "❌ Python 3 not found. Please install Python 3.11+"
    exit 1
fi

echo "✅ Using Python: $($python_cmd --version)"

# Get configuration from user
echo ""
echo "📋 Configuration"
echo "-----------------"

get_input "App port" "8443" "app_port"
get_input "App title" "Majic Movie Selector" "app_title"
get_input "Bind to all interfaces (0.0.0.0)" "0.0.0.0" "app_host"

# Optional API keys (can be left empty)
echo ""
echo "🔑 API Keys (optional - press Enter to skip)"
echo "-------------------------------------------"

get_input "TMDB API key" "" "tmdb_api_key"
get_input "Groq API key" "" "groq_api_key"
get_input "Plex base URL" "" "plex_base_url"
get_input "Plex token" "" "plex_token"

# Remove existing venv if it exists
if [ -d ".venv" ]; then
    echo "🗑️  Removing existing virtual environment..."
    rm -rf .venv
fi

# Create new virtual environment
echo "📦 Creating virtual environment..."
$python_cmd -m venv .venv

# Activate virtual environment and install dependencies
echo "⬇️  Installing dependencies..."
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Install additional dependencies for desktop app and MCP
echo "🔧 Installing additional dependencies..."
pip install mcp pywebview

# Make majic script executable
echo "🔑 Making majic script executable..."
chmod +x majic

# Create .env file automatically
echo "📝 Creating .env file..."
cat > .env << EOF
# App
APP_HOST=$app_host
APP_PORT=$app_port
APP_TITLE=$app_title

# Optional OpenAI integration (embeddings/explanations)
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# Optional TMDB integration for upcoming films
TMDB_API_KEY=$tmdb_api_key

# Optional Plex integration
PLEX_BASE_URL=$plex_base_url
PLEX_TOKEN=$plex_token

# Optional NZBGeek integration
NZBGEEK_RSS_URL=https://api.nzbgeek.info/api?t=search&cat=2000&apikey={API_KEY}
NZBGEEK_API_KEY=

# Optional DrunkenSlug integration
DRUNKENSLUG_BASE_URL=https://drunkenslug.com/api
DRUNKENSLUG_API_KEY=9c4445340c097b738f24233afc5ede34

# Groq (free tier)
GROQ_API_KEY=$groq_api_key
GROQ_MODEL=llama-3.3-70b-versatile

# Local AI (Ollama)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.3:70b-instruct-q4_K_M
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# Data and cache settings
DATA_DIR=data
MEMORY_DB_PATH=data/memory.db
EMBEDDING_DB_PATH=data/embeddings.db
CACHE_DIR=data/cache
LOG_LEVEL=INFO

# Performance settings
SOURCE_TIMEOUT_SECONDS=30
RECOMMENDATION_CACHE_TTL=300
AGENT_CACHE_TTL=300

# Feature flags
ENABLE_RAG=true
ENABLE_MCP=true
ENABLE_PLEX=true
ENABLE_USENET=true
EOF

echo ""
echo "🎉 Setup complete!"
echo ""
echo "🚀 Next steps:"
echo "1. ./majic ollama    # Auto-detect memory & download optimal model"
echo "2. ./majic dev       # Start the app"
echo ""
echo "🌐 Your app will be available at:"
if [[ "$app_host" == "0.0.0.0" ]]; then
    echo "   http://YOUR_IP:$app_port (accessible from other devices)"
else
    echo "   http://localhost:$app_port (local only)"
fi
echo ""
echo "📋 Available commands:"
echo "  ./majic dev        - Development mode"
echo "  ./majic start      - Production mode"
echo "  ./majic status     - Check status"
echo "  ./majic logs       - View logs"
echo "  ./majic ollama     - Smart model selector"
echo "  ./majic ollama list - Show available models"
echo ""
