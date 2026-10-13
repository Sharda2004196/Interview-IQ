"use client";

import React, { useState, useRef } from "react";
import { CloudArrowUp, CheckCircle, WarningCircle, FileText, Trash, SpinnerGap } from "@phosphor-icons/react";
import { uploadFile, type UploadResponse } from "@/lib/api";
import { TOKENS } from "@/lib/tokens";

interface FileUploadProps {
  label: string;
  description: string;
  namespace: string;
  onUploadSuccess: (namespace: string, response: UploadResponse) => void;
  onClear: () => void;
}

export function FileUpload({
  label,
  description,
  namespace,
  onUploadSuccess,
  onClear,
}: FileUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadedInfo, setUploadedInfo] = useState<UploadResponse | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    if (!file) return;
    setError(null);
    setIsUploading(true);

    const ns = namespace || `upload-${Date.now().toString(36)}`;

    try {
      const result = await uploadFile(file, ns);
      setUploadedInfo(result);
      onUploadSuccess(ns, result);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to upload file";
      setError(msg);
    } finally {
      setIsUploading(false);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFile(e.dataTransfer.files[0]);
    }
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleRemove = () => {
    setUploadedInfo(null);
    setError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
    onClear();
  };

  return (
    <div className="space-y-2">
      <div className="flex justify-between items-baseline">
        <label className="block text-xs font-medium uppercase tracking-wider text-zinc-500 dark:text-zinc-400 font-mono">
          {label}
        </label>
        {uploadedInfo && (
          <span className="text-[11px] font-mono text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
            <CheckCircle size={13} weight="fill" />
            <span>Indexed ({uploadedInfo.chunks} chunks)</span>
          </span>
        )}
      </div>

      {uploadedInfo ? (
        <div
          className={`flex items-center justify-between p-3.5 ${TOKENS.radius.card} border border-emerald-500/30 bg-emerald-500/5 dark:bg-emerald-500/10`}
        >
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 flex items-center justify-center shrink-0">
              <FileText size={18} weight="regular" />
            </div>
            <div className="min-w-0">
              <p className="text-xs font-medium text-zinc-900 dark:text-zinc-100 truncate">
                {uploadedInfo.file}
              </p>
              <p className="text-[11px] font-mono text-zinc-500 dark:text-zinc-400">
                {uploadedInfo.chars.toLocaleString()} chars · namespace: {uploadedInfo.namespace}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleRemove}
            aria-label="Remove uploaded file"
            className="p-1.5 rounded-md text-zinc-400 hover:text-rose-500 hover:bg-rose-500/10 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-rose-500/50"
          >
            <Trash size={16} weight="regular" />
          </button>
        </div>
      ) : (
        <div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onClick={() => fileInputRef.current?.click()}
          className={`relative border-2 border-dashed ${TOKENS.radius.card} p-5 text-center cursor-pointer transition-all duration-150 ${
            isDragging
              ? "border-emerald-500 bg-emerald-500/10"
              : "border-zinc-200 dark:border-white/10 hover:border-zinc-300 dark:hover:border-white/20 bg-zinc-50 dark:bg-zinc-900/40"
          } ${isUploading ? "pointer-events-none opacity-80" : ""}`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.txt,.md,.docx,.json"
            className="hidden"
            onChange={(e) => {
              if (e.target.files && e.target.files[0]) {
                handleFile(e.target.files[0]);
              }
            }}
          />

          <div className="flex flex-col items-center justify-center gap-2">
            {isUploading ? (
              <>
                <SpinnerGap size={24} weight="bold" className="animate-spin text-emerald-500" />
                <p className="text-xs font-medium text-zinc-700 dark:text-zinc-300">
                  Parsing &amp; indexing document chunks...
                </p>
              </>
            ) : (
              <>
                <div className="w-9 h-9 rounded-full bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center text-zinc-500 dark:text-zinc-400">
                  <CloudArrowUp size={20} weight="regular" />
                </div>
                <div>
                  <p className="text-xs font-medium text-zinc-800 dark:text-zinc-200">
                    Click to upload or drag &amp; drop
                  </p>
                  <p className="text-[11px] text-zinc-500 dark:text-zinc-400 mt-0.5">
                    {description}
                  </p>
                </div>
                <span className="text-[10px] font-mono text-zinc-400 dark:text-zinc-500 uppercase">
                  PDF, TXT, MD, DOCX
                </span>
              </>
            )}
          </div>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-1.5 text-xs text-rose-500 dark:text-rose-400 font-medium pt-1">
          <WarningCircle size={14} weight="fill" />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}
