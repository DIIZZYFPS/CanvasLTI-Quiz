import { cn } from "@/lib/utils"
import { useRef, useState } from "react"
import { File as FileIcon, Upload, X } from "lucide-react"
import { Button } from "./ui/button";
import { toast } from "sonner";

interface FileUploadProps {
    /** The chosen file. Owned by the parent so it survives switching input modes. */
    file: File | null;
    onChange: (file: File | null) => void;
    disabled?: boolean;
};

const ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.txt', '.md'];

export function FileUpload({ file, onChange, disabled = false }: FileUploadProps) {

    const [isDragOver, setIsDragOver] = useState(false);
    const inputRef = useRef<HTMLInputElement>(null);

    const validateAndSelectFile = (candidate: File) => {
        const ext = candidate.name.includes('.') ? candidate.name.slice(candidate.name.lastIndexOf('.')).toLowerCase() : '';
        if (!ALLOWED_EXTENSIONS.includes(ext)) {
            const extLabel = ext ? ` '${ext}'` : '';
            toast.error(`Unsupported file type${extLabel}. Please select a .pdf, .docx, .txt, or .md file.`);
            return false;
        }
        onChange(candidate);
        return true;
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        setIsDragOver(false);
        if (disabled) return;
        const files = Array.from(e.dataTransfer.files);
        if (files.length > 0) {
            validateAndSelectFile(files[0]);
        }
    }
    const handleDragOver = (e: React.DragEvent) => {
        e.preventDefault();
        if (!disabled) setIsDragOver(true);
    };

    const handleDragLeave = () => {
        setIsDragOver(false);
    };

    const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = e.target.files;
        if (files && files.length > 0) {
            validateAndSelectFile(files[0]);
        }
        // Allow choosing the same file again after removing it.
        e.target.value = "";
    };

  return (
    <div
      className={cn(
        "border-2 border-dashed rounded-lg p-8 text-center transition-colors",
        isDragOver ? "border-primary bg-primary/5" : "border-border",
        file && "border-primary/50 bg-primary/5"
      )}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
    >
      {file ? (
        <div className="flex items-center justify-between p-4 bg-background rounded-lg">
            <div className="flex items-center gap-3 min-w-0">
                <FileIcon className="h-6 w-6 shrink-0 text-primary" aria-hidden="true" />
                <div className="text-left min-w-0">
                    <p className="font-medium truncate">{file.name}</p>
                    <p className="text-sm text-muted-foreground">
                        {(file.size / 1024).toFixed(2)} KB
                        </p>
                </div>
            </div>
            <Button
                variant="ghost"
                size="sm"
                onClick={() => onChange(null)}
                disabled={disabled}
                aria-label={`Remove ${file.name}`}
                className="text-destructive hover:bg-destructive/10 hover:text-destructive"
            >
                <X className="h-4 w-4" aria-hidden="true" />
            </Button>
        </div>
      ) : (
        <div className="space-y-4">
            <Upload className="h-12 w-12 mx-auto text-muted-foreground" aria-hidden="true" />
            <div>
                <p className="text-sm text-muted-foreground">
                    Drag and drop a file here, or
                </p>
                <p className="text-sm text-muted-foreground">
                    click to browse (.pdf, .docx, .txt, .md)
                </p>
            </div>
            {/* The input stays hidden; a real <button> opens it. A hidden input plus a
                <label><span> has no keyboard path, so keyboard users could not pick a file. */}
            <input
                ref={inputRef}
                type="file"
                onChange={handleFileInput}
                className="hidden"
                id="file-upload"
                accept=".pdf,.docx,.txt,.md"
                tabIndex={-1}
                aria-hidden="true"
            />
            <Button
                type="button"
                variant="outline"
                disabled={disabled}
                onClick={() => inputRef.current?.click()}
            >
                Browse Files
            </Button>
        </div>
      )}
      </div>
  );
}
