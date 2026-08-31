# Chapter 1: Minimal Single-Agent System

## Goal

Build the smallest working Agent system from an empty directory. The system accepts command-line input and sends it to a large language model through AgentScope.

This chapter focuses on one execution path:

```text
Command-line input
    ↓
MainAgent
    ↓
ChatModel
    ↓
LLM service
    ↓
Final response
```

This chapter does not include product tools, databases, RAG, sub-agents, caching, WebSockets, or a frontend.

## Project Structure

```text
app/
├── application/
│   └── agents/
│       └── main_agent.py
├── domain/
├── infrastructure/
│   ├── settings.py
│   └── llm.py
├── presentation/
│   └── cli.py
└── composition.py
```

## Layer Responsibilities

### Presentation

`app/presentation/cli.py` accepts command-line input, converts the text into a `UserMsg`, invokes the MainAgent, and displays the final response.

### Application

`app/application/agents/main_agent.py` defines the Agent name, system prompt, model, and toolkit.

The toolkit is currently empty, so the Agent can only use the language capabilities of the model.

### Infrastructure

`app/infrastructure/settings.py` reads model configuration from environment variables.

`app/infrastructure/llm.py` uses that configuration to create an AgentScope `OpenAIChatModel`.

### Domain

There are no product or order business rules in this chapter, so the Domain layer is intentionally empty.

### Composition Root

`app/composition.py` assembles the settings, model, and MainAgent.

It connects dependencies but does not process user input or contain business rules.

## Core Concepts

### A Model Is Not an Agent

A ChatModel sends messages to an LLM service and receives responses.

An Agent adds the following capabilities around the model:

- Identity and system instructions
- Conversation state
- A toolkit
- A reasoning and tool-execution loop

### Dependency Injection

The MainAgent does not create its own model. It receives the model as an argument:

```python
def create_main_agent(model: OpenAIChatModel) -> Agent:
    ...
```

The Composition Root creates the model and injects it into the MainAgent.

This allows the model implementation to be replaced later without rewriting the main Agent definition.

### Separation of Presentation and Application Logic

Users currently interact with the system through the command line. A future HTTP API, WebSocket connection, or frontend can be added in the Presentation layer without rewriting the MainAgent.

## Running the Application

From the project root, run:

```bash
uv run python -m app.presentation.cli
```

Then enter a message at the command-line prompt.

## Current Limitations

- Only one command-line input is processed.
- There are no business tools.
- There is no product catalog.
- There is no multi-turn session management.
- Responses are not streamed.
- The Agent must not invent products, prices, inventory, or order information.

## Next Chapter

The next chapter will introduce the product domain model:

- Money value object
- SKU entity
- Product aggregate root
- ProductRepository port

These business objects will not depend on AgentScope or a specific database.