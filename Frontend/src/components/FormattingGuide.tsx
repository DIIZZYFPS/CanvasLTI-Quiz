import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

/** The "how to format your questions" card: always-visible essentials plus collapsible examples. */
export function FormattingGuide() {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
      <Collapsible open={isExpanded} onOpenChange={setIsExpanded}>
        <Card>
          <CardHeader>
            {/* A real <button> as the trigger: the old trigger was a <div>, which
                keyboards can't focus, and it wrapped the download link too. */}
            <CollapsibleTrigger asChild>
              <button
                type="button"
                className="flex w-full items-center justify-between gap-2 rounded-md text-left font-semibold leading-none outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
              >
                <span>Formatting Instructions</span>
                {isExpanded ? <ChevronUp className="w-5 h-5" aria-hidden="true" /> : <ChevronDown className="w-5 h-5" aria-hidden="true" />}
              </button>
            </CollapsibleTrigger>
            <CardDescription>
              Follow these guidelines for automatic type detection.
              <div className="mt-2 p-2 bg-warning/10 border border-warning/30 rounded-md text-warning font-medium text-xs">
                <span aria-hidden="true">⚠️ </span>IMPORTANT: You must leave at least one blank line between each question block.
              </div>
              <Separator className="my-2" />
              Our parser also natively supports the standard <b>Respondus Legacy Format</b> (Type: MC, MR, F, etc.).
            </CardDescription>
            <Button variant="outline" className="w-full mt-2" asChild>
              <a href="/api/instructions" download>Download formatting guide (.txt)</a>
            </Button>
          </CardHeader>
          <CollapsibleContent>
            <CardContent>
              <h3 className="text-sm font-semibold mb-3 px-1 text-primary">Simplified Core Format</h3>
              <Accordion type="single" collapsible className="w-full">
                <AccordionItem value="mc">
                  <AccordionTrigger>Multiple Choice / Answers</AccordionTrigger>
                  <AccordionContent>
                    <div className="space-y-4 text-sm pt-1 pb-3">
                      <div>
                        <p className="text-foreground font-medium">Multiple Choice (Single Answer):</p>
                        <div className="bg-muted/30 p-3 rounded-lg mt-1">
                          <pre className="text-xs text-muted-foreground whitespace-pre-wrap">{`What is 2+2?
    A) 3
    B) 4
    C) 5
    Answer: B`}</pre>
                        </div>
                      </div>
                      <div>
                        <p className="text-foreground font-medium">Multiple Answers (Multi-Select):</p>
                        <p className="text-muted-foreground text-xs mb-1">List multiple letters (A, B) or mark each with *</p>
                        <div className="bg-muted/30 p-3 rounded-lg">
                          <pre className="text-xs text-muted-foreground whitespace-pre-wrap">{`Select the even numbers:
  *A) 2
   B) 3
  *C) 4
  Answer: A, C`}</pre>
                        </div>
                      </div>
                    </div>
                  </AccordionContent>
                </AccordionItem>

                <AccordionItem value="tf" >
                  <AccordionTrigger >True/False</AccordionTrigger>
                  <AccordionContent>
                    <div className="space-y-2 text-sm pt-1 pb-3">
                      <p className="text-foreground">Start with "TF:" or end question with (T/F):</p>
                      <div className="bg-muted/30 p-3 rounded-lg">
                        <pre className="text-xs text-muted-foreground whitespace-pre-wrap">{`TF: The Earth is round.
    Answer: True`}</pre>
                      </div>
                    </div>
                  </AccordionContent>
                </AccordionItem>

                <AccordionItem value="sa">
                  <AccordionTrigger >Short Answer</AccordionTrigger>
                  <AccordionContent>
                    <div className="space-y-2 text-sm pt-1 pb-3">
                      <p className="text-foreground font-medium">Standard Style:</p>
                      <div className="bg-muted/30 p-3 rounded-lg">
                        <pre className="text-xs text-muted-foreground whitespace-pre-wrap">{`What year did WWII end?
  Answer: 1945`}</pre>
                      </div>
                    </div>
                  </AccordionContent>
                </AccordionItem>

                <AccordionItem value="essay" >
                  <AccordionTrigger >Essay Questions</AccordionTrigger>
                  <AccordionContent>
                    <div className="space-y-2 text-sm pt-1 pb-3">
                      <p className="text-foreground font-medium">Standard Style:</p>
                      <div className="bg-muted/30 p-3 rounded-lg">
                        <pre className="text-xs text-muted-foreground whitespace-pre-wrap">{`Essay: Explain the causes of World War I.
  Points: 10`}</pre>
                      </div>
                    </div>
                  </AccordionContent>
                </AccordionItem>

                <AccordionItem value="fmb" >
                  <AccordionTrigger >Multiple Blanks (FMB)</AccordionTrigger>
                  <AccordionContent>
                    <div className="space-y-4 text-sm pt-1 pb-3">
                      <div>
                        <p className="text-foreground font-medium">Auto-Blank Style (Easiest):</p>
                        <div className="bg-muted/30 p-3 rounded-lg mt-1">
                          <pre className="text-xs text-muted-foreground whitespace-pre-wrap">{`The capital of [France] is [Paris].`}</pre>
                        </div>
                      </div>
                      <div>
                        <p className="text-foreground font-medium">Mapped Style (For Synonyms):</p>
                        <div className="bg-muted/30 p-3 rounded-lg mt-1">
                          <pre className="text-xs text-muted-foreground whitespace-pre-wrap">{`The [color] jumped over the [animal].
  Answers: color: red, animal: dog`}</pre>
                        </div>
                      </div>
                    </div>
                  </AccordionContent>
                </AccordionItem>
              </Accordion>

              <p className="text-sm text-muted-foreground">Points can be specified anywhere in the question, e.g., "(5 pts)", "(10 points)", or "Points: 5".</p>
            </CardContent>
          </CollapsibleContent>
        </Card>
      </Collapsible>
  );
}
