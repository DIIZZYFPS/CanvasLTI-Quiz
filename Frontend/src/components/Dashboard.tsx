import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useState } from "react";
import { Upload, FileText, Download, CheckCircle, Clock, AlertCircle, Eye, X, ChevronDown, ChevronUp, Sun, Moon } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "./ui/collapsible";
import api from "@/api";
import { FileUpload } from "./FileUpload";
import { toast } from "sonner";
import { useTheme } from "./ui/theme-provider";

const Dashboard = () => {
  const [conversionStatus, setConversionStatus] = useState<'idle' | 'processing' | 'complete' | 'error'>('idle');
  const [progress, setProgress] = useState(0);
  const [quizContent, setQuizContent] = useState("");
  const [showPreview, setShowPreview] = useState(false);
  const [previewData, setPreviewData] = useState<any[]>([]);
  const [exportType, setExportType] = useState<'qti' | 'canvas'>('qti');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isExpanded, setIsExpanded] = useState(false);
  const { theme, setTheme } = useTheme();


  const handleFileUpload = (file: File) => {
    setSelectedFile(file);
  };

  const parseQuestions = async (content: string | null, file: File | null) => {
    if (!content && !file) return [];
    let response;

    if (file) {
      const formData = new FormData();
      formData.append('file', file);
      response = await api.post('/preview', formData);
    } else if (content) {
      response = await api.post('/preview', { quiz_text: content }, {
        headers: { 'Content-Type': 'application/json' }
      });
    }

    return response?.data?.questions ?? [];
  };

  const handleConvert = async (type: 'qti' | 'canvas') => {
    setExportType(type);
    setConversionStatus('processing');
    setProgress(0);
    console.log(quizContent)

    if (quizContent && selectedFile) {
      toast.error("Please provide either quiz content or a file, not both.");
      setConversionStatus('error');
      return;
    }
    // Simulate conversion progress
    const interval = setInterval(() => {
      setProgress(prev => {
        if (prev >= 100) {
          clearInterval(interval);
          setConversionStatus('complete');
          // Parse questions and show preview
          (async () => {
            const parsed = await parseQuestions(quizContent ? quizContent : null, selectedFile ? selectedFile : null);
            setPreviewData(parsed);
            setShowPreview(true);
          })();
          return 100;
        }
        return prev + 10;
      });
    }, 200);
  };

  const handleFinalExport = () => {
    setShowPreview(false);
    console.log(`Exporting ${previewData.length} questions as ${exportType}`);
    if (exportType === 'qti') {
      (async () => {
        let response;
        if (selectedFile) {
          const formData = new FormData();
          formData.append('file', selectedFile);
          response = await api.post('/download', formData, { responseType: 'blob' });
        }
        else if (quizContent) {
          response = await api.post('/download', { quiz_text: quizContent }, { responseType: 'blob' });
        }
        const blob = new Blob([response?.data], { type: 'application/zip' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'quiz_package.zip';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      })();
    }

  };

  const getStatusIcon = () => {
    switch (conversionStatus) {
      case 'processing': return <Clock className="w-4 h-4" />;
      case 'complete': return <CheckCircle className="w-4 h-4" />;
      case 'error': return <AlertCircle className="w-4 h-4" />;
      default: return <FileText className="w-4 h-4" />;
    }
  };

  const getStatusColor = () => {
    switch (conversionStatus) {
      case 'processing': return 'bg-primary';
      case 'complete': return 'bg-success';
      case 'error': return 'bg-destructive';
      default: return 'bg-muted';
    }
  };

  return (
    <div className="min-h-screen bg-gradient-subtle">
      {/* Header */}
      <header className="border-b bg-card/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="container mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-gradient-primary rounded-lg flex items-center justify-center">
                <FileText className="w-6 h-6 text-ring" />
              </div>
              <div>
                <h1 className="text-xl font-bold">Quiz to QTI Converter</h1>
                <p className="text-sm text-muted-foreground">Convert Canvas quiz questions to QTI format</p>
              </div>
            </div>
            <Badge variant="secondary" className="font-medium">
              Canvas LTI Tool
            </Badge>
            <Button onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} variant="ghost">
              {theme === 'dark' ? <Sun className='w-4 h-4' /> : <Moon className="w-4 h-4" /> }</Button>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-6 py-8 max-w-6xl">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Input Section */}
          <div className="lg:col-span-2 space-y-6">
            <Card className="shadow-card">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Upload className="w-5 h-5" />
                  Input Quiz Questions
                </CardTitle>
                <CardDescription>
                  Paste your Canvas quiz questions or upload a file to convert to QTI format
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* File Upload Component */}
                <FileUpload onSubmit={handleFileUpload} />
                
                <Separator />
                
                <div className="space-y-3">
                  <label htmlFor="quiz-content" className="text-sm font-medium">
                    Paste quiz content directly:
                  </label>
                  <Textarea
                    id="quiz-content"
                    placeholder="Paste your quiz questions here...&#10;&#10;Example Multiple Choice:&#10;What is the capital of France?&#10;A) London&#10;B) Berlin&#10;C) Paris&#10;D) Madrid&#10;Answer: C&#10;&#10;Example True/False:&#10;The Earth is flat. (T/F)&#10;Answer: False"
                    className="min-h-[200px] border-input-border focus:ring-2 focus:ring-primary"
                    value={quizContent}
                    onChange={(e) => setQuizContent(e.target.value)}
                  />
                </div>
              </CardContent>
            </Card>

            {/* Conversion Controls */}
            <Card className="shadow-card">
              <CardHeader>
                <CardTitle>Conversion Settings</CardTitle>
                <CardDescription>Configure your QTI export preferences</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <Button 
                    onClick={() => handleConvert('qti')}
                    disabled={(!quizContent.trim() && !selectedFile) || conversionStatus === 'processing'}
                    variant="outline"
                    className="bg-gradient-primary hover:shadow-glow transition-all duration-300 col-span-1 md:col-span-2"
                  >
                    Export to QTI ZIP
                  </Button>
                  {/*
                  <Button 
                    onClick={() => handleConvert('canvas')}
                    disabled={(!quizContent.trim() && !selectedFile) || conversionStatus === 'processing' true } // Disable Canvas export for now
                    variant="outline"
                    className="border-primary text-primary hover:bg-primary hover:text-primary-foreground"
                  >
                    Export to Canvas Quiz (Coming Soon)
                  </Button>
                  */} 
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Status & Output Section */}
          <div className="space-y-6">
            

            {/* Formatting Instructions */}
            <Collapsible open={isExpanded} onOpenChange={setIsExpanded}>
              <Card className="shadow-card">
                <CollapsibleTrigger asChild>
                <CardHeader> 
                  <CardTitle className="flex items-center justify-between w-full">
                    Formatting Instructions 
                    {isExpanded ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
                  </CardTitle>
                  <CardDescription>
                    Format your questions according to these guidelines for automatic type detection
                  </CardDescription>
                  <CardFooter>
                    <Button variant="outline" className="w-full">
                      <a href="/api/instructions" download>Download AI Formatting Guide</a>
                    </Button>
                  </CardFooter>
                </CardHeader>
              </CollapsibleTrigger>
                <CollapsibleContent>
                <CardContent>
                  <div className="space-y-4 text-sm">
                    <div className="space-y-2">
                      <h2 className="font-medium text-primary">Multiple Choice</h2>
                      <div className="bg-muted/30 p-3 rounded-lg">
                        <p className="mb-2">List options with A) B) C) D) and indicate the correct answer:</p>
                        <pre className="text-xs text-muted-foreground whitespace-pre-wrap">What is 2+2?
  A) 3
  B) 4
  C) 5
  D) 6
  Answer: B</pre>
                      </div>
                    </div>

                    <div className="space-y-2">
                      <h2 className="font-medium text-primary">True/False</h2>
                      <div className="bg-muted/30 p-3 rounded-lg">
                        <p className="mb-2">End question with (T/F) or True/False:</p>
                        <pre className="text-xs text-muted-foreground whitespace-pre-wrap">The Earth is round. (T/F)
  Answer: True</pre>
                      </div>
                    </div>

                    <div className="space-y-2">
                      <h2 className="font-medium text-primary">Short Answer</h2>
                      <div className="bg-muted/30 p-3 rounded-lg">
                        <p className="mb-2">Start with "SA:" or end with [Short Answer]:</p>
                        <pre className="text-xs text-muted-foreground whitespace-pre-wrap">SA: What year did WWII end?
  Answer: 1945</pre>
                      </div>
                    </div>

                    <div className="space-y-2">
                      <h2 className="font-medium text-primary">Essay Questions</h2>
                      <div className="bg-muted/30 p-3 rounded-lg">
                        <p className="mb-2">Start with "Essay:" or end with [Essay]:</p>
                        <pre className="text-xs text-muted-foreground whitespace-pre-wrap">Essay: Explain the causes of World War I.
  Points: 10</pre>
                      </div>
                    </div>

                    <div className="space-y-2">
                      <h2 className="font-medium text-primary">Fill in the Blank</h2>
                      <div className="bg-muted/30 p-3 rounded-lg">
                        <p className="mb-2">Use _____ for blanks:</p>
                        <pre className="text-xs text-muted-foreground whitespace-pre-wrap">The capital of France is _____.
  Answer: Paris</pre>
                      </div>
                    </div>
                  </div>
                </CardContent>
                </CollapsibleContent>
              </Card>
            </Collapsible>

            {/* Status Card */}
            <Card className="shadow-card">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  {getStatusIcon()}
                  Conversion Status
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className={`p-4 rounded-lg ${getStatusColor()}/10 border border-current/20`}>
                  <div className="flex items-center gap-2 mb-2">
                    <div className={`w-2 h-2 rounded-full ${getStatusColor()}`} />
                    <span className="font-medium capitalize">{conversionStatus}</span>
                  </div>
                  {conversionStatus === 'processing' && (
                    <Progress value={progress} className="mt-2" />
                  )}
                  {conversionStatus === 'complete' && (
                    <p className="text-sm text-muted-foreground">
                      Successfully converted to QTI format
                    </p>
                  )}
                </div>

                {conversionStatus === 'complete' && (
                  <div className="space-y-3">
                    <Button 
                      onClick={() => setShowPreview(true)}
                      variant="default" 
                      className="w-full bg-gradient-accent"
                    >
                      <Eye className="w-4 h-4 mr-2" />
                      View Preview
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>

          </div>
        </div>
      </main>

      {/* Preview Dialog */}
      <Dialog open={showPreview} onOpenChange={setShowPreview}>
        <DialogContent className="max-w-4xl max-h-[80vh]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Eye className="w-5 h-5" />
              Preview Questions ({previewData.length} questions)
            </DialogTitle>
            <DialogDescription>
              Review your converted questions before exporting to {exportType.toUpperCase()}
            </DialogDescription>
          </DialogHeader>
          
          <ScrollArea className="h-[50vh] pr-4">
            <div className="space-y-4">
              {previewData.map((question, index) => (
                <Card key={question.id} className="border-l-4 border-l-primary">
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between">
                      <Badge variant="secondary" className="text-xs">
                        {index + 1} - {question.type?.replace(/_/g, ' ').toUpperCase()}
                      </Badge>
                      <Badge variant="outline" className="text-xs">
                        {question.points} {question.points > 1 ? "points" : "point"}
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent className="pt-0 space-y-3">
                    <p className="font-medium">{question.question_text || question.question}</p>

                    {/* Render answers if present */}
                    {Array.isArray(question.answers) && question.answers.length > 1 && (
                      <div className="space-y-1">
                        {question.answers.map((ans: any, optIndex: number) => (
                          <div
                            key={optIndex}
                            className={`p-2 rounded text-sm ${
                              ans.id === question.correct_answer_id
                                ? 'bg-green-400/10 border border-green-400/50'
                                : 'bg-muted/30'
                            }`}
                          >
                            {ans.text}
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Fallback for single answer */}
                    {question.answers && (
                      <div className="text-sm">
                        <span className="font-medium text-primary">Answer: </span>
                        <span className="text-muted-foreground">
                          {question.correct_answer_id ? (
                            Array.isArray(question.answers)
                              ? question.answers.find((ans: any) => ans.id === question.correct_answer_id)?.text
                              : question.answers?.text
                          ) : question.answers[0]?.text}
                        </span>
                      </div>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          </ScrollArea>
          
          <DialogFooter className="flex gap-3">
            <Button
              variant="outline"
              onClick={() => setShowPreview(false)}
              className="flex items-center gap-2"
            >
              <X className="w-4 h-4" />
              Cancel
            </Button>
            <Button
              onClick={handleFinalExport}
              className="bg-gradient-primary hover:shadow-glow flex items-center gap-2"
            >
              <Download className="w-4 h-4" />
              Export {exportType.toUpperCase()}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Dashboard;