import { cn } from "@/lib/utils"
import {useState} from "react"
import { File, Upload, X } from "lucide-react"
import { Button } from "./ui/button";

interface FileUploadProps {
    onSubmit: (file: File) => void;
};

export function FileUpload({ onSubmit }: FileUploadProps) {

    const [isDragOver, setIsDragOver] = useState(false);
    const [selectedFile, setSelectedFile] = useState<File | null>(null);


    const handleFileSelect = (file: File) => {
        setSelectedFile(file);
         onSubmit(file);
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        setIsDragOver(false);
        const files = Array.from(e.dataTransfer.files);
        if (files.length > 0) {
            handleFileSelect(files[0]);
        }
    }
    const handleDragOver = (e: React.DragEvent) => {
        e.preventDefault();
        setIsDragOver(true);
    };

    const handleDragLeave = () => {
        setIsDragOver(false);
    };

    const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = e.target.files;
        if (files && files.length > 0) {
            handleFileSelect(files[0]);
        }
    };

    const removeFile = () => {
        setSelectedFile(null);
        onSubmit(null as unknown as File);
    };

  return (
    <div
      className={cn(
        "border-2 border-dashed rounded-lg p-8 text-center transition-colors",
        isDragOver ? "border-primary bg-primary/5" : "border-border",
        selectedFile && "border-yellow-500 bg-yellow-50/50"
      )}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
    >
      {selectedFile ? (
        <div className="flex items-center justify-between p-4 bg-background rounded-lf">
            <div className="flex items-center gap-3">
                <File className="h-6 w-6 text-primary" />
                <div className="text-left">
                    <p className="font-medium">{selectedFile.name}</p>
                    <p className="text-sm text-muted-foreground">
                        {(selectedFile.size / 1024).toFixed(2)} KB
                        </p>
                </div>
            </div>
            <Button
                variant="ghost"
                size="sm"
                onClick={removeFile}
                className="text-red-500 hover:bg-red-50"
            >
                <X className="h-4 w-4" />
            </Button>
        </div>
      ) : (
        <div className="space-y-4">
            <Upload className="h-12 w-12 mx-auto text-muted-foreground" />
            <div>
                <p className="text-sm text-muted-foreground">
                    Drag and drop a file here, or
                </p>
                <p className="text-sm text-muted-foreground">
                    click to browse
                </p>
            </div>
            <input
                type="file"
                onChange={handleFileInput}
                className="hidden"
                id="file-upload"
                accept=".pdf,.doc,.docx,.txt,.csv,.xlsx"
            />
            <label htmlFor="file-upload">
                <Button variant="outline" className="cursor-pointer" asChild>
                    <span>Browse Files</span>
                </Button>
            </label>
        </div>
      )}
      </div>
  );
}