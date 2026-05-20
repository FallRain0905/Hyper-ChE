import { useEffect, useRef, useState, useCallback } from 'react';
import { getWebSocketUrl } from '../utils';

export interface WebSocketHookReturn {
  isConnected: boolean;
  sendMessage: (message: any) => void;
  reconnect: () => void;
}

export const useWebSocket = (onMessage?: (data: any) => void): WebSocketHookReturn => {
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const onMessageRef = useRef(onMessage);

  // 更新onMessage引用
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  const connect = useCallback(() => {
    const wsUrl = getWebSocketUrl('/ws');
    console.log('[WebSocket] 连接中...', wsUrl);

    try {
      wsRef.current = new WebSocket(wsUrl);

      wsRef.current.onopen = () => {
        console.log('[WebSocket] 连接成功');
        setIsConnected(true);
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
          reconnectTimeoutRef.current = null;
        }
      };

      wsRef.current.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          console.log('[WebSocket] 收到消息:', data);

          // 处理数据库更新通知
          if (data.type === 'database_deleted' && onMessageRef.current) {
            onMessageRef.current(data);
          }
        } catch (error) {
          console.error('[WebSocket] 解析消息失败:', error);
        }
      };

      wsRef.current.onclose = () => {
        console.log('[WebSocket] 连接关闭');
        setIsConnected(false);
        // 5秒后尝试重连
        reconnectTimeoutRef.current = setTimeout(() => {
          console.log('[WebSocket] 5秒后尝试重连...');
          connect();
        }, 5000);
      };

      wsRef.current.onerror = (error) => {
        console.error('[WebSocket] 连接错误:', error);
      };
    } catch (error) {
      console.error('[WebSocket] 创建连接失败:', error);
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  const sendMessage = useCallback((message: any) => {
    if (wsRef.current && isConnected) {
      wsRef.current.send(JSON.stringify(message));
    } else {
      console.warn('[WebSocket] 未连接，无法发送消息');
    }
  }, [isConnected]);

  const reconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
    }
    connect();
  }, [connect]);

  return { isConnected, sendMessage, reconnect };
};
