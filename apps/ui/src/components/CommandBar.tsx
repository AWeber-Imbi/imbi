import { useState, useRef, useEffect } from 'react'
import { Send, ChevronUp, ChevronDown, X, Sparkles, Mic } from 'lucide-react'

interface CommandBarProps {
  isDarkMode: boolean
}

interface Message {
  id: string
  type: 'user' | 'assistant'
  content: string
  timestamp: Date
}

export function CommandBar({ isDarkMode }: CommandBarProps) {
  const [input, setInput] = useState('')
  const [isExpanded, setIsExpanded] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [isListening, setIsListening] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (isExpanded && messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, isExpanded])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim()) return

    // Add user message
    const userMessage: Message = {
      id: Date.now().toString(),
      type: 'user',
      content: input,
      timestamp: new Date()
    }
    setMessages(prev => [...prev, userMessage])

    // Simulate AI response
    setTimeout(() => {
      const aiMessage: Message = {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: getAIResponse(input),
        timestamp: new Date()
      }
      setMessages(prev => [...prev, aiMessage])
    }, 500)

    setInput('')

    // Expand if not already expanded
    if (!isExpanded) {
      setIsExpanded(true)
    }
  }

  const getAIResponse = (userInput: string): string => {
    const lower = userInput.toLowerCase()

    if (lower.includes('deploy') || lower.includes('deployment')) {
      return 'I can help you with deployments. Recent deployments show activity across Testing, Staging, and Production environments. Would you like to see deployment details for a specific project or environment?'
    }
    if (lower.includes('project')) {
      return 'I found several projects in the system. You can view all projects, search by name, or filter by namespace. What would you like to know about?'
    }
    if (lower.includes('health') || lower.includes('status')) {
      return 'System health looks good. Most projects have high health scores. I can show you projects with health concerns or specific metrics if needed.'
    }
    if (lower.includes('user') || lower.includes('who')) {
      return 'I can look up user information, recent activity, and project ownership. What user would you like to know about?'
    }
    if (lower.includes('help')) {
      return 'I can help you with:\n• Finding and managing projects\n• Deployment information and history\n• System health and metrics\n• User lookup and activity\n• Navigation and search\n\nWhat would you like to explore?'
    }

    return 'I understand you\'re asking about "' + userInput + '". I can help you navigate Imbi, find projects, check deployments, and more. Try asking about projects, deployments, or type "help" for more options.'
  }

  const handleClearHistory = () => {
    setMessages([])
  }

  const handleVoiceClick = () => {
    setIsListening(!isListening)
    // In a real implementation, this would start/stop speech recognition
  }

  const formatTime = (date: Date) => {
    return date.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true
    })
  }

  return (
    <>
      {/* Conversation Panel */}
      <div
        className={`fixed bottom-16 left-0 right-0 transition-transform duration-300 ease-out ${
          isExpanded ? 'translate-y-0' : 'translate-y-full'
        } ${isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'} border-t shadow-2xl`}
        style={{ height: '60vh', maxHeight: '600px' }}
      >
        {/* Panel Header */}
        <div className={`flex items-center justify-between px-6 py-3 border-b ${
          isDarkMode ? 'border-gray-700 bg-gray-750' : 'border-gray-200 bg-gray-50'
        }`}>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            <span className={`text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
              AI Assistant
            </span>
            {messages.length > 0 && (
              <span className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                • {messages.length} message{messages.length !== 1 ? 's' : ''}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {messages.length > 0 && (
              <button
                onClick={handleClearHistory}
                className={`text-xs px-2 py-1 rounded ${
                  isDarkMode
                    ? 'text-gray-400 hover:text-gray-300 hover:bg-gray-700'
                    : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                }`}
              >
                Clear
              </button>
            )}
            <button
              onClick={() => setIsExpanded(false)}
              className={`p-1 rounded ${
                isDarkMode
                  ? 'text-gray-400 hover:text-gray-300 hover:bg-gray-700'
                  : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
              }`}
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className={`h-full overflow-y-auto p-6 space-y-4 ${
          isDarkMode ? 'bg-gray-800' : 'bg-white'
        }`} style={{ height: 'calc(100% - 52px)' }}>
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full">
              <div className={`text-6xl mb-4 ${isDarkMode ? 'text-gray-600' : 'text-gray-300'}`}>
                <Sparkles className="w-16 h-16" />
              </div>
              <h3 className={`text-xl mb-2 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                AI Assistant Ready
              </h3>
              <p className={`text-center max-w-md ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                Ask me anything about your projects, deployments, health scores, or navigation.
              </p>
              <div className={`mt-4 space-y-2 text-sm ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                <div>Try: "Show me recent deployments"</div>
                <div>Try: "What projects have low health scores?"</div>
                <div>Try: "Who owns the jira-triage project?"</div>
              </div>
            </div>
          ) : (
            <>
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`flex ${message.type === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div className={`max-w-[80%] ${message.type === 'user' ? 'order-2' : ''}`}>
                    <div className={`flex items-center gap-2 mb-1 ${
                      message.type === 'user' ? 'justify-end' : 'justify-start'
                    }`}>
                      <span className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                        {message.type === 'user' ? 'You' : 'AI'}
                      </span>
                      <span className={`text-xs ${isDarkMode ? 'text-gray-600' : 'text-gray-300'}`}>
                        {formatTime(message.timestamp)}
                      </span>
                    </div>
                    <div
                      className={`rounded-lg px-4 py-2 whitespace-pre-wrap ${
                        message.type === 'user'
                          ? isDarkMode
                            ? 'bg-blue-600 text-white'
                            : 'bg-[#2A4DD0] text-white'
                          : isDarkMode
                            ? 'bg-gray-750 text-gray-200'
                            : 'bg-gray-100 text-gray-900'
                      }`}
                    >
                      {message.content}
                    </div>
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </>
          )}
        </div>
      </div>

      {/* Command Bar */}
      <div className={`fixed bottom-0 left-0 right-0 z-50 transition-colors ${
        isDarkMode ? 'bg-gray-900 border-gray-700' : 'bg-white border-gray-200'
      } border-t`}>
        {/* Tray Toggle */}
        <div className="flex justify-center">
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className={`-mt-3 px-6 py-1 rounded-t-lg border border-b-0 transition-all ${
              isDarkMode
                ? 'bg-gray-800 border-gray-700 text-gray-400 hover:text-gray-300'
                : 'bg-white border-gray-200 text-gray-600 hover:text-gray-900'
            } ${isExpanded ? 'shadow-lg' : ''}`}
          >
            {isExpanded ? (
              <ChevronDown className="w-4 h-4" />
            ) : (
              <div className="flex items-center gap-2">
                <ChevronUp className="w-4 h-4" />
                {messages.length > 0 && (
                  <span className={`w-2 h-2 rounded-full bg-blue-500 ${
                    isDarkMode ? '' : 'animate-pulse'
                  }`} />
                )}
              </div>
            )}
          </button>
        </div>

        {/* Input Bar */}
        <form onSubmit={handleSubmit} className="px-6 py-3">
          <div className={`flex items-center gap-3 p-2 rounded-lg border ${
            isDarkMode
              ? 'bg-gray-800 border-gray-600 focus-within:border-blue-500'
              : 'bg-gray-50 border-gray-300 focus-within:border-[#2A4DD0]'
          } transition-colors`}>
            <div className={`flex items-center gap-2 px-2 ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
              <span className="text-sm font-mono">{'>'}</span>
            </div>
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Search for projects, ask about deployments, health, or type 'help'..."
              className={`flex-1 bg-transparent outline-none text-sm ${
                isDarkMode
                  ? 'text-white placeholder:text-gray-500'
                  : 'text-gray-900 placeholder:text-gray-400'
              }`}
            />

            {/* Voice Button */}
            <button
              type="button"
              onClick={handleVoiceClick}
              className={`w-8 h-8 rounded-full flex items-center justify-center transition-all ${
                isListening
                  ? 'bg-red-500 text-white animate-pulse'
                  : isDarkMode
                    ? 'bg-gray-900 text-gray-400 hover:bg-gray-950 hover:text-white border border-gray-700'
                    : 'bg-gray-900 text-gray-300 hover:bg-black hover:text-white'
              }`}
              title={isListening ? 'Stop listening' : 'Start voice input'}
            >
              <Mic className="w-4 h-4" />
            </button>

            {/* Send Button */}
            {input.trim() && (
              <button
                type="submit"
                className={`p-2 rounded transition-colors ${
                  isDarkMode
                    ? 'text-blue-400 hover:bg-gray-700'
                    : 'text-[#2A4DD0] hover:bg-gray-200'
                }`}
              >
                <Send className="w-4 h-4" />
              </button>
            )}
          </div>
          <div className={`flex items-center justify-between mt-2 px-2 text-xs ${
            isDarkMode ? 'text-gray-600' : 'text-gray-400'
          }`}>
            <span>Press Enter to send</span>
            <span className="flex items-center gap-1">
              <Sparkles className="w-3 h-3" />
              AI-powered
            </span>
          </div>
        </form>
      </div>
    </>
  )
}
