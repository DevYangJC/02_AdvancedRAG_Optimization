/**
 * 知识库管理 API(仅 admin 可用,普通用户调用后端返回 403)。
 * 覆盖文档列表、批量上传、删除、分块查看与运营统计,是管理页面的数据来源。
 */
import client from './client'
import type { AdminStats, ChunkItem, DocumentItem, Paged } from '@/types/api'

export const documentApi = {
  // keyword 为文件名模糊搜索:列表页搜索框直接复用该参数,无需单独搜索接口。
  list(page = 1, page_size = 20, keyword?: string) {
    return client.get<Paged<DocumentItem>>('/documents', { params: { page, page_size, keyword } })
  },
  // 批量上传:多个文件打包成一个 FormData,一次请求全部入库(后端逐个解析)。
  upload(files: File[]) {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return client.post<{ uploaded: number }>('/documents/upload', form, {
      timeout: 0, // 大文件上传不限时
    })
  },
  // 删除文档会级联清空其全部向量(后端异步执行),被删除内容将不再被检索到。
  remove(id: string) {
    return client.delete(`/documents/${id}`)
  },
  // 查看文档切分后的知识块:排查"为什么没检索到"时,可对照块内容与搜索词。
  listChunks(id: string, page = 1, page_size = 50) {
    return client.get<Paged<ChunkItem>>(`/documents/${id}/chunks`, { params: { page, page_size } })
  },
  // 运营统计(文档数/知识块数/用户数):展示在管理页顶部的指标卡片。
  stats() {
    return client.get<AdminStats>('/documents/admin/stats')
  },
}
