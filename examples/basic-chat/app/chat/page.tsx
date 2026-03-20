import React from 'react';
import { useAgent } from '../../../packages/freeride-react/hooks';
import { Concierge } from '../../agents/concierge';

export default function ChatPage() {
  const { messages, reasoning, input, setInput, submit, status } = useAgent(Concierge);

  return (
    <div className="flex flex-col h-screen bg-gray-100 p-4">
      <header className="mb-4">
        <h1 className="text-2xl font-bold">FreeRide Concierge</h1>
        <p className="text-sm text-gray-500">Status: {status}</p>
      </header>

      <div className="flex-1 overflow-y-auto bg-white rounded-lg shadow p-4 mb-4">
        {messages.map((m: any) => (
          <div key={m.id} className={`mb-4 ${m.role === 'user' ? 'text-right' : 'text-left'}`}>
            <div className={`inline-block p-3 rounded-lg ${m.role === 'user' ? 'bg-blue-500 text-white' : 'bg-gray-200 text-black'}`}>
              {m.content}
            </div>
          </div>
        ))}
        {status === 'thinking' && (
          <div className="text-gray-400 italic">Thinking...</div>
        )}
      </div>

      <div className="bg-gray-50 p-4 rounded-lg mb-4">
        <h2 className="text-sm font-semibold mb-2">Reasoning Logs</h2>
        {reasoning.map((r: any) => (
          <div key={r.id} className="text-xs text-gray-600 mb-1">
            [{new Date(r.timestamp).toLocaleTimeString()}] {r.thought}
          </div>
        ))}
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          className="flex-1 p-2 border rounded-lg"
          placeholder="Type your message..."
        />
        <button
          onClick={submit}
          className="bg-blue-500 text-white px-4 py-2 rounded-lg hover:bg-blue-600"
        >
          Send
        </button>
      </div>
    </div>
  );
}
