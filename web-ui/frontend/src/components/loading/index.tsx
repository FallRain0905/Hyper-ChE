import React from 'react'
import styles from './index.module.less'

const Loading: React.FC = props => {
  return (
    <main className={styles.box} aria-live="polite" aria-busy="true">
      <div className={styles.texture} aria-hidden="true" />
      <section className={styles.container} aria-label="正在载入 HyperChE">
        <div className={styles.brand}>
          <span className={styles.mark} aria-hidden="true">
            <svg viewBox="0 0 44 44" role="presentation">
              <path d="M22 3 39 13v18L22 41 5 31V13Z" />
              <path d="M13 15h18M13 29h18M13 15v14M31 15v14" />
              <circle cx="22" cy="22" r="3.5" />
            </svg>
          </span>
          <span>
            <b>HyperChE</b>
            <small>化工知识检索与问答</small>
          </span>
        </div>
        <div className={styles.visual} aria-hidden="true">
          <span className={`${styles.node} ${styles.nodeA}`} />
          <span className={`${styles.node} ${styles.nodeB}`} />
          <span className={`${styles.node} ${styles.nodeC}`} />
          <span className={`${styles.node} ${styles.nodeD}`} />
          <span className={styles.edge} />
          <span className={`${styles.edge} ${styles.edgeSecond}`} />
          <div className={styles.orbit} />
          <div className={styles.core}>HC</div>
        </div>
        <p className={styles.kicker}>CHEMICAL KNOWLEDGE · HYPERGRAPH RETRIEVAL</p>
        <h1>正在载入知识工作台</h1>
        <p className={styles.message}>准备检索环境与证据视图</p>
        <div className={styles.dots} aria-hidden="true"><i /><i /><i /></div>
      </section>
    </main>
  )
}

// Loading.defaultProps = {
//   imgUrl: loading
// }

export default Loading
