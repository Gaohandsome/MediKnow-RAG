import { defineStore } from 'pinia'
import { apiSystem } from '@/api'

const DEFAULT_DISCLAIMER =
  '以上内容依据院内知识库资料整理，仅供医疗专业人员参考，不能替代执业医师的诊断与处方。'

export const useSafetyStore = defineStore('safety', {
  state: () => ({
    disclaimer: DEFAULT_DISCLAIMER,
    disclaimerEnabled: true,
    redFlagEnabled: true,
    loaded: false,
  }),
  actions: {
    async load(force = false) {
      if (this.loaded && !force) return
      try {
        const data = await apiSystem.safetyConfig()
        this.disclaimer = data.disclaimer || DEFAULT_DISCLAIMER
        this.disclaimerEnabled = data.disclaimer_enabled !== false
        this.redFlagEnabled = data.red_flag_enabled !== false
      } catch {
        /* 接口不可用时沿用默认文案 */
      } finally {
        this.loaded = true
      }
    },
  },
})
