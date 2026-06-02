/**
 * WebSocket client for real-time release updates
 */
import type { WSMessage } from '../types/api'

type MessageHandler = (message: WSMessage) => void

export class ReleaseWebSocket {
  private ws: WebSocket | null = null
  private releaseId: string
  private handlers: Set<MessageHandler> = new Set()
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectDelay = 1000

  constructor(releaseId: string) {
    this.releaseId = releaseId
  }

  /**
   * Connect to the WebSocket server
   */
  connect(): void {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = import.meta.env.VITE_WS_URL || `${protocol}//${window.location.host}`
    const url = `${host}/api/releases/ws/${this.releaseId}`

    this.ws = new WebSocket(url)

    this.ws.onopen = () => {
      console.log(`WebSocket connected for release ${this.releaseId}`)
      this.reconnectAttempts = 0
    }

    this.ws.onmessage = (event) => {
      try {
        const message: WSMessage = JSON.parse(event.data)
        this.handlers.forEach((handler) => handler(message))
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error)
      }
    }

    this.ws.onclose = (event) => {
      console.log(`WebSocket closed: ${event.code} ${event.reason}`)
      if (!event.wasClean && this.reconnectAttempts < this.maxReconnectAttempts) {
        this.reconnectAttempts++
        const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1)
        console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`)
        setTimeout(() => this.connect(), delay)
      }
    }

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error)
    }
  }

  /**
   * Disconnect from the WebSocket server
   */
  disconnect(): void {
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    this.handlers.clear()
    this.reconnectAttempts = this.maxReconnectAttempts // Prevent reconnection
  }

  /**
   * Add a message handler
   */
  onMessage(handler: MessageHandler): () => void {
    this.handlers.add(handler)
    return () => this.handlers.delete(handler)
  }

  /**
   * Check if connected
   */
  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }
}

/**
 * Create and manage a WebSocket connection for a release
 */
export function createReleaseWebSocket(releaseId: string): ReleaseWebSocket {
  const ws = new ReleaseWebSocket(releaseId)
  ws.connect()
  return ws
}
