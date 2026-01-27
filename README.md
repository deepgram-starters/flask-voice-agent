# Flask Voice Agent Starter

Start building interactive voice experiences with Deepgram's Voice Agent API using Python Flask starter application. This project demonstrates how to create a voice agent that can engage in natural conversations using Deepgram's advanced AI capabilities.

## What is Deepgram?

[Deepgram's](https://deepgram.com/) voice AI platform provides APIs for speech-to-text, text-to-speech, and full speech-to-speech voice agents. Over 200,000+ developers use Deepgram to build voice AI products and features.

## Sign-up to Deepgram

Before you start, it's essential to generate a Deepgram API key to use in this project. [Sign-up now for Deepgram and create an API key](https://console.deepgram.com/signup?jump=keys).

## Prerequisites

- Python 3.8 or higher
- Node.js 14.0.0+ and pnpm 10.0.0+ (for frontend)
- Deepgram API key
- Modern web browser with microphone support

## Quickstart

Follow these steps to get started with this starter application.

### Clone the repository

Clone the repository with submodules (the frontend is a shared submodule):

```bash
git clone --recurse-submodules https://github.com/deepgram-starters/flask-voice-agent.git
cd flask-voice-agent
```

### Initialize the project

Using the Makefile (recommended - handles venv and submodule setup):

```bash
make init
```

The `make init` command will:
- Initialize the frontend submodule
- Create a Python virtual environment
- Install backend dependencies
- Install frontend dependencies

### Configure your API key

Copy the sample environment file and add your Deepgram API key:

```bash
cp sample.env .env
# Edit .env and add your DEEPGRAM_API_KEY
```

### Start development servers

```bash
make dev
```

This starts both:
- Flask backend on `http://localhost:8080` (serves API and proxies to Vite)
- Vite dev server on `http://localhost:5173` (internal, provides HMR)

**Important:** Always access the app at `http://localhost:8080` (not 5173).

The backend proxies all requests to Vite for hot module reloading, while Vite proxies API routes back to the backend.

### Using the application

1. Open your browser to `http://localhost:8080`
2. Allow microphone access when prompted
3. Speak into your microphone to interact with the Deepgram Voice Agent
4. You should hear the agent's responses played back in your browser

## Available Make Commands

- `make help` - Show all available commands
- `make init` - Initialize submodules and install dependencies
- `make dev` - Start development servers
- `make build` - Build frontend for production
- `make start` - Start production server
- `make clean` - Remove dependencies and build artifacts
- `make update` - Update submodules to latest commits
- `make status` - Show git and submodule status

## Production Deployment

To build for production:

```bash
make build
make start
```

In production mode, the Flask backend serves the pre-built static frontend from `frontend/dist/`.

## Using Cursor & MDC Rules

This application can be modify as needed by using the [app-requirements.mdc](.cursor/rules/app-requirements.mdc) file. This file allows you to specify various settings and parameters for the application in a structured format that can be use along with [Cursor's](https://www.cursor.com/) AI Powered Code Editor.

### Using the `app-requirements.mdc` File

1. Clone or Fork this repo.
2. Modify the `app-requirements.mdc`
3. Add the necessary configuration settings in the file.
4. You can refer to the MDC file used to help build this starter application by reviewing  [app-requirements.mdc](.cursor/rules/app-requirements.mdc)

## Testing

Test the application with:

```bash
pytest -v test_app.py
```

## Getting Help

We love to hear from you so if you have questions, comments or find a bug in the project, let us know! You can either:

- [Open an issue in this repository](https://github.com/deepgram-starters/flask-voice-agent/issues/new)
- [Join the Deepgram Github Discussions Community](https://github.com/orgs/deepgram/discussions)
- [Join the Deepgram Discord Community](https://discord.gg/xWRaCDBtW4)

## Contributing

We welcome contributions! Please see our [Contributing Guidelines](./CONTRIBUTING.md) for details.

## Security

For security concerns, please see our [Security Policy](./SECURITY.md).

## Code of Conduct

Please see our [Code of Conduct](./CODE_OF_CONDUCT.md) for community guidelines.

## Author

[Deepgram](https://deepgram.com)

## License

This project is licensed under the MIT license. See the [LICENSE](./LICENSE) file for more info.
