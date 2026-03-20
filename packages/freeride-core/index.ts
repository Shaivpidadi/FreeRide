export type Message = {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  timestamp: number;
};

export type ReasoningStep = {
  id: string;
  thought: string;
  action?: string;
  observation?: string;
  timestamp: number;
};

export type AgentStatus = 'idle' | 'thinking' | 'streaming' | 'error';

export type AgentConfig = {
  name: string;
  model: string;
  instructions: string;
  tools?: Record<string, any>;
};
