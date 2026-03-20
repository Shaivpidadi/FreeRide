import { useState, useEffect, useRef, useCallback } from 'react';
import { Message, ReasoningStep, AgentStatus } from '../freeride-core';

export function useAgent(agent: any) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [reasoning, setReasoning] = useState<ReasoningStep[]>([]);
  const [input, setInput] = useState('');
  const [status, setStatus] = useState<AgentStatus>('idle');

  // Streaming Shadow DOM (SSD) - Buffering tokens outside React state
  const tokenBuffer = useRef<string[]>([]);
  const currentResponseId = useRef<string | null>(null);
  const rafId = useRef<number | null>(null);

  // Flush buffer to state using requestAnimationFrame
  const flushBuffer = useCallback(() => {
    if (tokenBuffer.current.length > 0) {
      const newTokens = tokenBuffer.current.join('');
      tokenBuffer.current = [];

      setMessages(prev => {
        const lastMessage = prev[prev.length - 1];
        if (lastMessage && lastMessage.id === currentResponseId.current) {
          return [
            ...prev.slice(0, -1),
            { ...lastMessage, content: lastMessage.content + newTokens }
          ];
        } else {
          return [
            ...prev,
            {
              id: currentResponseId.current!,
              role: 'assistant',
              content: newTokens,
              timestamp: Date.now()
            }
          ];
        }
      });
    }
    rafId.current = requestAnimationFrame(flushBuffer);
  }, []);

  useEffect(() => {
    rafId.current = requestAnimationFrame(flushBuffer);
    return () => {
      if (rafId.current) cancelAnimationFrame(rafId.current);
    };
  }, [flushBuffer]);

  const submit = async () => {
    if (!input.trim()) return;

    const userMessage: Message = {
      id: Math.random().toString(36).substring(7),
      role: 'user',
      content: input,
      timestamp: Date.now()
    };

    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setStatus('thinking');

    const stream = await agent.submit(input);
    const reader = stream.getReader();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = JSON.parse(value);
      if (chunk.type === 'reasoning') {
        setReasoning(prev => [...prev, chunk.data]);
      } else if (chunk.type === 'token') {
        setStatus('streaming');
        currentResponseId.current = chunk.id;
        tokenBuffer.current.push(chunk.content);
      }
    }

    setStatus('idle');
  };

  return {
    messages,
    reasoning,
    input,
    setInput,
    submit,
    status
  };
}
