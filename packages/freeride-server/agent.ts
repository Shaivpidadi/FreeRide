import { AgentConfig, Message, ReasoningStep } from '../freeride-core';

export class Agent {
  private config: AgentConfig;
  private messages: Message[] = [];
  private reasoning: ReasoningStep[] = [];

  constructor(config: AgentConfig) {
    this.config = config;
  }

  async submit(input: string): Promise<ReadableStream> {
    // Add user message
    const userMessage: Message = {
      id: Math.random().toString(36).substring(7),
      role: 'user',
      content: input,
      timestamp: Date.now(),
    };
    this.messages.push(userMessage);

    // Create a readable stream for the response
    const stream = new ReadableStream({
      start: async (controller) => {
        // Simulate thinking
        const reasoningStep: ReasoningStep = {
          id: Math.random().toString(36).substring(7),
          thought: `Analyzing user input: "${input}"`,
          timestamp: Date.now(),
        };
        this.reasoning.push(reasoningStep);
        controller.enqueue(JSON.stringify({ type: 'reasoning', data: reasoningStep }));

        // Simulate streaming tokens
        const responseId = Math.random().toString(36).substring(7);
        const tokens = ["Hello!", " I", " am", " your", " AI", " assistant.", " How", " can", " I", " help", " you", " today?"];
        
        for (const token of tokens) {
          await new Promise(resolve => setTimeout(resolve, 50)); // Simulate latency
          controller.enqueue(JSON.stringify({ type: 'token', id: responseId, content: token }));
        }

        controller.close();
      }
    });

    return stream;
  }

  getMessages() {
    return this.messages;
  }

  getReasoning() {
    return this.reasoning;
  }
}

export function tool(config: { params: any; execute: (params: any) => Promise<any>; description: string }) {
  return config;
}
