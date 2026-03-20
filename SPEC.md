# FreeRide: Technical Specification for an AI-Native Runtime

## 1. Executive Summary
FreeRide represents a fundamental shift in web framework architecture, transitioning from a component-centric model to an **agent-centric** paradigm. While traditional frameworks like React and Next.js were designed for static or user-driven state transitions, FreeRide is built from the ground up to handle the non-deterministic, high-frequency, and state-heavy nature of generative AI. This specification outlines the core architectural components, API surfaces, and runtime optimizations that define the FreeRide ecosystem.

## 2. Core Architectural Components

### 2.1 Agent-Centric Routing (ACR)
Traditional web routing relies on a static mapping between URL paths and UI components. FreeRide evolves this concept through **Agent-Centric Routing (ACR)**, which introduces a semantic layer between the user's intent and the application's response. The **Semantic Router** utilizes high-dimensional embeddings to analyze user queries and dynamically route them to the most appropriate agent or page. This allows for a more fluid user experience where the application adapts to the user's needs in real-time, rather than forcing the user to navigate a predefined hierarchy.

| Component | Traditional Routing | Agent-Centric Routing |
| :--- | :--- | :--- |
| **Primary Key** | URL Path (e.g., `/settings`) | User Intent (e.g., "Change my theme") |
| **Mapping** | Path -> Component | Intent -> Agent/Action |
| **Resolution** | Deterministic (Regex/String) | Probabilistic (Semantic Similarity) |
| **State** | Stateless | Context-Aware |

### 2.2 Streaming Shadow DOM (SSD)
One of the primary bottlenecks in current AI applications is the "re-render chaos" caused by high-frequency token streaming. When an LLM generates 30-50 tokens per second, each token typically triggers a full reconciliation cycle in traditional virtual DOMs, leading to significant UI jank and main-thread blocking. FreeRide addresses this through the **Streaming Shadow DOM (SSD)**, a specialized, non-blocking state tree that operates independently of the main UI render loop.

The SSD buffers incoming tokens in a high-performance mutable structure and flushes updates to the UI using **requestAnimationFrame (RAF)** batching. This ensures that the application remains responsive at 60 frames per second, even during intense streaming operations. Furthermore, the SSD supports **Direct-to-DOM Slots**, allowing the framework to bypass the virtual DOM entirely for specific streaming elements, writing directly to the underlying DOM nodes for maximum efficiency.

### 2.3 Unified Intelligence Layer (UIL)
The **Unified Intelligence Layer (UIL)** integrates vector databases and embedding models directly into the framework's data access layer. Unlike traditional stacks where vector search is treated as an external service, FreeRide's **Vector ORM** allows developers to define semantic schemas as first-class citizens. This integration enables **Automatic Retrieval-Augmented Generation (RAG)**, where the framework automatically identifies relevant context from the database based on the agent's current task and injects it into the prompt pipeline.

| Feature | Traditional Stack | FreeRide UIL |
| :--- | :--- | :--- |
| **Data Types** | String, Int, JSON | String, Int, **Vector(n)** |
| **Search** | Keyword/Exact Match | **Semantic/Similarity** |
| **Context** | Manual Fetch & Inject | **Automatic RAG Injection** |
| **Prompts** | Hardcoded Strings | **Versioned .prompt Files** |

### 2.4 Deterministic Agentic Flows (DAF)
To ensure reliability in agentic behavior, FreeRide provides **Deterministic Agentic Flows (DAF)**. This suite of primitives includes the `useReasoning()` hook, which exposes an agent's internal "Chain of Thought" (CoT) as a separate, observable stream. This allows developers to build transparent UIs that show the agent's progress without cluttering the primary message history. Additionally, the **Toolbox** provides a type-safe registry for external functions, with native support for the **Model Context Protocol (MCP)**, enabling seamless integration with a vast ecosystem of third-party tools.

## 3. API Surface and Developer Experience

### 3.1 Server-Side Primitives
The primary unit of compute in FreeRide is the **Agent**. An agent is defined by its model configuration, system instructions, and a set of tools. The `tool()` function allows for the definition of type-safe operations using **Zod** schema validation, ensuring that the LLM's interactions with external systems are always structured and predictable. Database tables are defined using the `defineTable()` primitive, which supports native vector columns for embedding storage.

### 3.2 Client-Side Hooks
On the client side, the `useAgent()` hook provides a unified interface for interacting with server-side agents. It returns a reactive state object containing the message history, current input, submission handlers, and the agent's reasoning logs. For more specialized needs, the `useVectorSearch()` hook allows for direct semantic queries from the UI, while the `useReasoning()` hook provides deep visibility into the agent's internal decision-making process.

## 4. Runtime Performance and Deployment
FreeRide is designed for the modern edge-first deployment model. It supports **Zero-Config Streaming** out of the box, utilizing Server-Sent Events (SSE) or WebSockets depending on the requirements. The framework is optimized for low-latency execution on edge platforms like Vercel and Cloudflare, but it also includes a **Long-Running Bridge** that allows complex agentic tasks to transition seamlessly from a fast edge response to a persistent background process. This ensures that the user receives immediate feedback while the agent continues to work on complex, multi-step objectives in the background.
