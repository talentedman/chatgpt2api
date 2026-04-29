"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Copy,
  ImageIcon,
  LoaderCircle,
  Maximize2,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { DateRangeFilter } from "@/components/date-range-filter";
import { ImageLightbox } from "@/components/image-lightbox";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { deleteManagedImages, fetchManagedImages, type ManagedImage } from "@/lib/api";
import { formatServerDateTime } from "@/lib/datetime";
import { useAuthGuard } from "@/lib/use-auth-guard";

function formatSize(size: number) {
  return size > 1024 * 1024 ? `${(size / 1024 / 1024).toFixed(2)} MB` : `${Math.ceil(size / 1024)} KB`;
}

function ImageManagerContent() {
  const [items, setItems] = useState<ManagedImage[]>([]);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [lightboxIndex, setLightboxIndex] = useState(0);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [lightboxItems, setLightboxItems] = useState<
    Array<{ id: string; src: string; sizeLabel?: string; dimensions?: string; prompt?: string }>
  >([]);
  const [page, setPage] = useState(1);
  const [dimensions, setDimensions] = useState<Record<string, string>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [selectedPaths, setSelectedPaths] = useState<string[]>([]);
  const [deletingPaths, setDeletingPaths] = useState<string[]>([]);

  const deletingPathSet = useMemo(() => new Set(deletingPaths), [deletingPaths]);
  const lightboxImages = items.map((item) => ({
    id: item.path || item.name,
    src: item.url,
    sizeLabel: formatSize(item.size),
    dimensions: dimensions[item.url],
    prompt: item.prompt,
  }));
  const pageSize = 12;
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const currentRows = items.slice((safePage - 1) * pageSize, safePage * pageSize);
  const currentPagePaths = currentRows.map((item) => item.path).filter(Boolean);
  const allCurrentPageSelected =
    currentPagePaths.length > 0 && currentPagePaths.every((path) => selectedPaths.includes(path));

  const openLightbox = (
    images: Array<{ id: string; src: string; sizeLabel?: string; dimensions?: string; prompt?: string }>,
    index: number,
  ) => {
    if (!images.length) return;
    const safeIndex = Math.max(0, Math.min(index, images.length - 1));
    setLightboxItems(images);
    setLightboxIndex(safeIndex);
    setLightboxOpen(true);
  };

  const loadImages = async () => {
    setIsLoading(true);
    try {
      const data = await fetchManagedImages({ start_date: startDate, end_date: endDate });
      setItems(data.items);
      setPage(1);
      setSelectedPaths([]);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载图片失败");
    } finally {
      setIsLoading(false);
    }
  };

  const clearFilters = () => {
    setStartDate("");
    setEndDate("");
  };

  const toggleSelected = (path: string, checked: boolean) => {
    setSelectedPaths((current) => {
      if (checked) {
        return current.includes(path) ? current : [...current, path];
      }
      return current.filter((item) => item !== path);
    });
  };

  const toggleCurrentPage = () => {
    if (allCurrentPageSelected) {
      setSelectedPaths((current) => current.filter((path) => !currentPagePaths.includes(path)));
      return;
    }
    setSelectedPaths((current) => Array.from(new Set([...current, ...currentPagePaths])));
  };

  const handleDelete = async (paths: string[]) => {
    const normalized = Array.from(new Set(paths.map((item) => String(item || "").trim()).filter(Boolean)));
    if (normalized.length === 0) {
      return;
    }
    if (!window.confirm(`确认删除 ${normalized.length} 张图片吗？删除后无法恢复。`)) {
      return;
    }

    setDeletingPaths((current) => Array.from(new Set([...current, ...normalized])));
    try {
      const result = await deleteManagedImages(normalized);
      if (result.errors?.length) {
        toast.warning(`已删除 ${result.removed} 张，${result.errors.length} 张删除失败`);
      } else {
        toast.success(`已删除 ${result.removed} 张图片`);
      }
      if (result.missing?.length) {
        toast.warning(`${result.missing.length} 张图片不存在或已删除`);
      }
      setSelectedPaths((current) => current.filter((path) => !normalized.includes(path)));
      await loadImages();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除图片失败");
    } finally {
      setDeletingPaths((current) => current.filter((path) => !normalized.includes(path)));
    }
  };

  useEffect(() => {
    void loadImages();
  }, [startDate, endDate]);

  return (
    <section className="space-y-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-1">
          <div className="text-xs font-semibold tracking-[0.18em] text-stone-500 uppercase">Images</div>
          <h1 className="text-2xl font-semibold tracking-tight">图片管理</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <DateRangeFilter startDate={startDate} endDate={endDate} onChange={(start, end) => { setStartDate(start); setEndDate(end); }} />
          <Button variant="outline" onClick={clearFilters} className="h-10 rounded-xl border-stone-200 bg-white px-4 text-stone-700">
            清除筛选条件
          </Button>
          <Button onClick={() => void loadImages()} disabled={isLoading} className="h-10 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800">
            {isLoading ? <LoaderCircle className="size-4 animate-spin" /> : <Search className="size-4" />}
            查询
          </Button>
        </div>
      </div>

      <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
        <CardContent className="p-0">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-stone-100 px-5 py-4">
            <div className="flex items-center gap-2 text-sm text-stone-600">
              <ImageIcon className="size-4" />
              共 {items.length} 张
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                className="h-8 rounded-lg border-stone-200 bg-white px-3 text-stone-600"
                onClick={toggleCurrentPage}
                disabled={currentPagePaths.length === 0}
              >
                {allCurrentPageSelected ? "取消本页全选" : "全选本页"}
              </Button>
              <Button
                variant="outline"
                className="h-8 rounded-lg border-rose-200 bg-rose-50 px-3 text-rose-700 hover:bg-rose-100"
                onClick={() => void handleDelete(selectedPaths)}
                disabled={selectedPaths.length === 0 || deletingPaths.length > 0}
              >
                {deletingPaths.length > 0 ? <LoaderCircle className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                删除选中 ({selectedPaths.length})
              </Button>
              <Button variant="ghost" className="h-8 rounded-lg px-3 text-stone-500" onClick={() => void loadImages()} disabled={isLoading}>
                <RefreshCw className={`size-4 ${isLoading ? "animate-spin" : ""}`} />
                刷新
              </Button>
            </div>
          </div>
          <div className="grid gap-0 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {currentRows.map((item) => {
              const imageIndex = items.findIndex((row) => row.url === item.url);
              const imagePath = item.path || item.name;
              const selected = selectedPaths.includes(imagePath);
              const deleting = deletingPathSet.has(imagePath);
              const promptText = String(item.prompt || "").trim();
              const showReferenceImage = item.request_type === "edit" && Boolean(item.reference_image_url);
              return (
                <div key={item.url} className="group border-r border-b border-stone-100 p-4 transition hover:bg-stone-50">
                  <div className="relative">
                    <button
                      type="button"
                      className="relative block aspect-square w-full cursor-zoom-in overflow-hidden rounded-lg bg-stone-100 text-left"
                      onClick={() => {
                        openLightbox(lightboxImages, imageIndex);
                      }}
                    >
                      <img
                        src={item.url}
                        alt={item.name}
                        className="h-full w-full object-cover transition group-hover:scale-[1.02]"
                        onLoad={(event) => {
                          const image = event.currentTarget;
                          setDimensions((current) => ({
                            ...current,
                            [item.url]: `${image.naturalWidth} x ${image.naturalHeight}`,
                          }));
                        }}
                      />
                      <span className="absolute right-2 bottom-2 rounded-full bg-black/50 p-2 text-white opacity-0 transition group-hover:opacity-100">
                        <Maximize2 className="size-4" />
                      </span>
                    </button>
                    <label className="absolute left-2 top-2 inline-flex items-center gap-1 rounded-md bg-black/45 px-1.5 py-1 text-white">
                      <input
                        type="checkbox"
                        checked={selected}
                        onChange={(event) => toggleSelected(imagePath, event.target.checked)}
                        className="size-3.5 accent-stone-900"
                      />
                    </label>
                  </div>
                  <div className="mt-3 space-y-2 text-xs text-stone-500">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1 font-medium text-stone-700">
                        <CalendarDays className="size-3.5" />
                        {formatServerDateTime(item.created_at)}
                      </div>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-8 rounded-lg text-stone-400 hover:bg-stone-100 hover:text-stone-700"
                          onClick={() => {
                            void navigator.clipboard.writeText(item.url);
                            toast.success("图片地址已复制");
                          }}
                        >
                          <Copy className="size-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-8 rounded-lg text-rose-500 hover:bg-rose-50 hover:text-rose-700"
                          onClick={() => void handleDelete([imagePath])}
                          disabled={deleting}
                        >
                          {deleting ? <LoaderCircle className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                        </Button>
                      </div>
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <span>{formatSize(item.size)}</span>
                      <span>{dimensions[item.url] || "-"}</span>
                    </div>
                    {showReferenceImage ? (
                      <div className="space-y-1">
                        <div className="text-[11px] font-medium text-stone-500">参考图：</div>
                        <button
                          type="button"
                          className="group relative block h-24 w-24 cursor-zoom-in overflow-hidden rounded-md border border-stone-200 bg-stone-100 text-left"
                          onClick={() =>
                            openLightbox(
                              [{ id: `${imagePath}-reference`, src: String(item.reference_image_url || ""), prompt: promptText }],
                              0,
                            )
                          }
                        >
                          <img
                            src={item.reference_image_url}
                            alt="参考图"
                            className="h-24 w-24 object-cover transition group-hover:scale-[1.02]"
                          />
                          <span className="absolute right-1.5 bottom-1.5 rounded-full bg-black/50 p-1 text-white opacity-0 transition group-hover:opacity-100">
                            <Maximize2 className="size-3.5" />
                          </span>
                        </button>
                      </div>
                    ) : null}
                    <div className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1.5 text-[11px] leading-4 text-stone-600">
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <span className="font-medium text-stone-500">提示词：</span>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 rounded-md px-2 text-[11px] text-stone-500 hover:bg-stone-100"
                          onClick={() => {
                            void navigator.clipboard.writeText(promptText);
                            toast.success("提示词已复制");
                          }}
                          disabled={!promptText}
                        >
                          <Copy className="size-3.5" />
                          复制
                        </Button>
                      </div>
                      <span
                        style={{
                          display: "-webkit-box",
                          WebkitLineClamp: 3,
                          WebkitBoxOrient: "vertical",
                          overflow: "hidden",
                        }}
                      >
                        {promptText || "（暂无记录）"}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="flex items-center justify-end gap-2 border-t border-stone-100 px-4 py-3 text-sm text-stone-500">
            <span>第 {safePage} / {pageCount} 页，共 {items.length} 张</span>
            <Button variant="outline" size="icon" className="size-9 rounded-lg border-stone-200 bg-white" disabled={safePage <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>
              <ChevronLeft className="size-4" />
            </Button>
            <Button variant="outline" size="icon" className="size-9 rounded-lg border-stone-200 bg-white" disabled={safePage >= pageCount} onClick={() => setPage((value) => Math.min(pageCount, value + 1))}>
              <ChevronRight className="size-4" />
            </Button>
          </div>
          {!isLoading && items.length === 0 ? <div className="px-6 py-14 text-center text-sm text-stone-500">没有找到图片</div> : null}
        </CardContent>
      </Card>
      <ImageLightbox
        images={lightboxItems}
        currentIndex={lightboxIndex}
        open={lightboxOpen}
        onOpenChange={setLightboxOpen}
        onIndexChange={setLightboxIndex}
      />
    </section>
  );
}

export default function ImageManagerPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);
  if (isCheckingAuth || !session || session.role !== "admin") {
    return <div className="flex min-h-[40vh] items-center justify-center"><LoaderCircle className="size-5 animate-spin text-stone-400" /></div>;
  }
  return <ImageManagerContent />;
}
