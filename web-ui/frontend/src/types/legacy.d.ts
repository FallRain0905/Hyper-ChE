// Types retained by the original admin/store integration.
declare namespace User {
  interface UserEntity {
    username: string
    roles: Array<{ id: number; name: string; description: string; adminCount: number; status: number; sort: number }>
    [key: string]: unknown
  }
}
declare namespace Global {
  interface ResultType<T = unknown> {
    code: number
    message: string
    data: T
  }
}
