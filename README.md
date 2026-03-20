# FreeRide: The AI-Native JavaScript Framework

## 1. Introduction
**FreeRide** is a first-of-its-kind, AI-native JavaScript/TypeScript framework designed for the agentic era. While traditional frameworks like React, Next.js, and Vue were developed before the AI revolution, FreeRide is built from the ground up to integrate intelligence into the core runtime, routing, and state management. By treating AI as a first-class primitive, FreeRide overcomes the limitations of pre-AI frameworks, providing a seamless developer experience and superior runtime performance for LLM-powered applications.

## 2. Core Philosophy
The fundamental philosophy of FreeRide is that **AI is a capability, not a feature**. In a traditional stack, AI is often treated as an external API call, leading to fragmented state management, inefficient streaming, and disconnected data layers. FreeRide addresses these challenges by introducing several novel architectural patterns:

| Pattern | Description |
| :--- | :--- |
| **Agent-Centric Routing (ACR)** | Routes are defined by user intent rather than static URL paths, allowing for dynamic, context-aware navigation. |
| **Streaming Shadow DOM (SSD)** | A high-performance, non-blocking state tree that buffers LLM tokens and updates the UI via `requestAnimationFrame` batching. |
| **Unified Intelligence Layer (UIL)** | A built-in Vector ORM that integrates embeddings, indexing, and semantic search directly into the data layer. |
| **Deterministic Agentic Flows (DAF)** | Primitives for reliable agent behavior, including `useReasoning()`, type-safe `Toolbox`, and native MCP support. |

## 3. Key Features

### 3.1 Agent-Centric Routing (ACR)
In FreeRide, the primary unit of application logic is the **Agent**, not the **Page**. The framework's **Semantic Router** uses high-dimensional embeddings to match user queries to the most relevant agent or action. This allows for a more fluid user experience where the application adapts to the user's needs in real-time, rather than forcing the user to navigate a predefined hierarchy.

### 3.2 Streaming Shadow DOM (SSD)
To solve the "re-render chaos" of high-frequency LLM tokens, FreeRide introduces the **Streaming Shadow DOM (SSD)**. This specialized state tree buffers incoming tokens and flushes updates to the UI using **requestAnimationFrame (RAF)** batching. This ensures that the application remains responsive at 60 frames per second, even during intense streaming operations, by preventing the main UI render loop from being overwhelmed by frequent state updates.

### 3.3 Unified Intelligence Layer (UIL)
The **Unified Intelligence Layer (UIL)** integrates vector databases and embedding models directly into the framework's data access layer. FreeRide's **Vector ORM** allows developers to define semantic schemas as first-class citizens, enabling **Automatic Retrieval-Augmented Generation (RAG)**. The framework automatically identifies relevant context from the database based on the agent's current task and injects it into the prompt pipeline, significantly reducing the complexity of building context-aware applications.

## 4. Quick Start

### 4.1 Define an Agent (`/agents/concierge.ts`)
```typescript
import { Agent, tool } from 'freeride/server';
import { z } from 'zod';

export const Concierge = new Agent({
  name: 'Concierge',
  model: 'gpt-4o',
  instructions: 'You are a helpful hotel concierge.',
  tools: {
    bookRoom: tool({
      params: z.object({ date: z.string(), type: z.string() }),
      execute: async ({ date, type }) => { /* ... */ }
    })
  }
});
```

### 4.2 Use in UI (`/app/chat/page.tsx`)
```tsx
import { useAgent } from 'freeride/react';
import { Concierge } from '@/agents/concierge';

export default function ChatPage() {
  const { messages, input, submit, reasoning } = useAgent(Concierge);

  return (
    <main>
      <ReasoningView data={reasoning} />
      <MessageList data={messages} />
      <ChatInput value={input} onSend={submit} />
    </main>
  );
}
```

## 5. License
FreeRide is released under the **MIT License**.
