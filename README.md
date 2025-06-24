# Flask Voice Agent Starter

Start building interactive voice experiences with Deepgram's Voice Agent API using Python Flask starter application. This project demonstrates how to create a voice agent that can engage in natural conversations using Deepgram's advanced AI capabilities.

## What is Deepgram?

[Deepgram's](https://deepgram.com/) voice AI platform provides APIs for speech-to-text, text-to-speech, and full speech-to-speech voice agents. Over 200,000+ developers use Deepgram to build voice AI products and features.

## Sign-up to Deepgram

Before you start, it's essential to generate a Deepgram API key to use in this project. [Sign-up now for Deepgram and create an API key](https://console.deepgram.com/signup?jump=keys).

## Prerequisites

- Python 3.8 or higher
- Deepgram API key
- Modern web browser with microphone support
- [Port Audio](https://www.portaudio.com/) installed locally

## Quickstart

Follow these steps to get started with this starter application.

### Clone the repository

1. Go to GitHub and [clone the repository](https://github.com/deepgram-starters/flask-voice-agent).

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set your Deepgram API key:
```bash
export DEEPGRAM_API_KEY=your_api_key_here
```

## Running the Application

Start the Flask server:
```bash
python app.py
```

Then open your browser and go to:

```
http://localhost:3000
```

- Allow microphone access when prompted.
- Speak into your microphone to interact with the Deepgram Voice Agent.
- You should hear the agent's responses played back in your browser.

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

## Issue Reporting

- [Open an issue in this repository](https://github.com/deepgram-starters/flask-voice-agent/issues/new)
- [Join the Deepgram Github Discussions Community](https://github.com/orgs/deepgram/discussions)
- [Join the Deepgram Discord Community](https://discord.gg/xWRaCDBtW4)

## Author

[Deepgram](https://deepgram.com)

## License

This project is licensed under the MIT license. See the [LICENSE](./LICENSE) file for more info.
