import { Button, Result } from 'antd'
import React from 'react'
import type { NotFoundPropsType } from './type'

const NotFound: React.FC<NotFoundPropsType> = ({
  status = '404',
  title = '404',
  subTitle = '对不起！您访问的页面不存在',
  extra = (
    <Button type="primary">
      <a href="/">返回首页</a>
    </Button>
  )
}) => {
  return (
    <>
      <Result status={status} title={title} subTitle={subTitle} extra={extra} />
    </>
  )
}

export default NotFound
