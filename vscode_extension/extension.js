const vscode = require('vscode');
const fs = require('fs');
const path = require('path');

let docs = {
    functions: {},
    constants: {},
    keywords: {},
    types: {},
    snippets: []
};

function loadDocs(extensionPath) {
    try {
        const docsPath = path.join(extensionPath, 'arena_docs.json');
        if (fs.existsSync(docsPath)) {
            const raw = fs.readFileSync(docsPath, 'utf8');
            docs = JSON.parse(raw);
            console.log(`Arena Language Support: Loaded ${Object.keys(docs.functions).length} functions, ${Object.keys(docs.constants).length} constants.`);
        } else {
            console.warn(`Arena Language Support: arena_docs.json not found at ${docsPath}`);
        }
    } catch (err) {
        console.error('Arena Language Support: Error loading documentation:', err);
    }
}

function formatItemHover(item) {
    const md = new vscode.MarkdownString();
    md.isTrusted = true;

    if (item.signature) {
        md.appendCodeblock(item.signature, 'arena');
    } else {
        md.appendCodeblock(item.name, 'arena');
    }

    if (item.category) {
        md.appendMarkdown(`*${item.category}*\n\n`);
    }

    if (item.description) {
        md.appendMarkdown(`${item.description}\n\n`);
    }

    if (item.parameters && item.parameters.length > 0) {
        md.appendMarkdown(`**Parametreler:**\n`);
        for (const p of item.parameters) {
            md.appendMarkdown(`- \`${p.label || p.name}\`: ${p.documentation || ''}\n`);
        }
        md.appendMarkdown('\n');
    }

    if (item.returns) {
        md.appendMarkdown(`**Dönüş Değeri:** ${item.returns}\n\n`);
    } else if (item.returnType && item.returnType !== 'void') {
        md.appendMarkdown(`**Dönüş Değeri:** \`${item.returnType}\`\n\n`);
    }

    if (item.example) {
        md.appendMarkdown(`**Örnek:**\n`);
        md.appendCodeblock(item.example, 'arena');
    }

    return md;
}

function formatFallbackHover(word) {
    const md = new vscode.MarkdownString();
    md.isTrusted = true;

    if (word.startsWith('nb_')) {
        md.appendCodeblock(`mixed ${word}(...)`, 'arena');
        md.appendMarkdown(`*NetModule Router SDK API Fonksiyonu*\n\n`);
        md.appendMarkdown(`Bu fonksiyon NetModule Router SDK (NRSW) donanım, ağ veya sistem yönetim arayüzüne aittir.\n\n`);
        md.appendMarkdown(`**Kullanım:**\n`);
        md.appendCodeblock(`result = ${word}(...);`, 'arena');
        md.appendMarkdown(`*Cihazınızdaki NB SDK API Kılavuzu'na (v5.0+) başvurabilirsiniz.*\n`);
        return md;
    }

    md.appendCodeblock(`${word}(...)`, 'arena');
    md.appendMarkdown(`*Arena / Standart Fonksiyon*\n\n`);
    md.appendMarkdown(`Arena betik dili veya C çalışma zamanında tanımlı fonksiyon ya da kullanıcı fonksiyonu.\n`);
    return md;
}

function getFunctionCallContext(document, position) {
    let depth = 0;
    let paramIndex = 0;
    const maxLines = 15;
    const startLine = position.line;
    const endChar = position.character;

    for (let l = startLine; l >= 0 && (startLine - l) < maxLines; l--) {
        const text = document.lineAt(l).text;
        const slice = (l === startLine) ? text.substring(0, endChar) : text;

        for (let i = slice.length - 1; i >= 0; i--) {
            const char = slice[i];

            if (char === ')') {
                depth++;
            } else if (char === '(') {
                if (depth > 0) {
                    depth--;
                } else {
                    let prefix = slice.substring(0, i).trim();
                    let funcLine = l;
                    while (!prefix && funcLine > 0) {
                        funcLine--;
                        prefix = document.lineAt(funcLine).text.trim();
                    }
                    const match = prefix.match(/([a-zA-Z_][a-zA-Z0-9_]*)\s*$/);
                    if (match) {
                        return {
                            functionName: match[1],
                            paramIndex: paramIndex
                        };
                    }
                    return null;
                }
            } else if (char === ',' && depth === 0) {
                paramIndex++;
            }
        }
    }
    return null;
}

function activate(context) {
    loadDocs(context.extensionPath);

    // 1. Hover Provider
    const hoverProvider = vscode.languages.registerHoverProvider('arena', {
        provideHover(document, position, token) {
            const range = document.getWordRangeAtPosition(position, /[a-zA-Z_][a-zA-Z0-9_]*/);
            if (!range) return null;

            const word = document.getText(range);
            const item = (docs.functions && docs.functions[word]) ||
                         (docs.constants && docs.constants[word]) ||
                         (docs.keywords && docs.keywords[word]) ||
                         (docs.types && docs.types[word]);

            if (item) {
                return new vscode.Hover(formatItemHover(item), range);
            }

            // Fallback for unknown functions
            const lineText = document.lineAt(position.line).text;
            const afterWord = lineText.substring(range.end.character).trim();
            const isCall = afterWord.startsWith('(');

            if (word.startsWith('nb_') || isCall) {
                return new vscode.Hover(formatFallbackHover(word), range);
            }

            return null;
        }
    });

    // 2. Completion Item Provider (IntelliSense Autocomplete)
    const completionProvider = vscode.languages.registerCompletionItemProvider('arena', {
        provideCompletionItems(document, position, token, context) {
            const items = [];

            // Functions
            if (docs.functions) {
                for (const [name, fn] of Object.entries(docs.functions)) {
                    const item = new vscode.CompletionItem(name, vscode.CompletionItemKind.Function);
                    item.detail = fn.signature || `${name}()`;
                    item.documentation = new vscode.MarkdownString(fn.description || '');

                    if (fn.parameters && fn.parameters.length > 0) {
                        const paramPlaceholders = fn.parameters.map((p, idx) => `\${${idx + 1}:${p.name}}`).join(', ');
                        item.insertText = new vscode.SnippetString(`${name}(${paramPlaceholders})`);
                    } else {
                        item.insertText = new vscode.SnippetString(`${name}()`);
                    }
                    items.push(item);
                }
            }

            // Constants
            if (docs.constants) {
                for (const [name, c] of Object.entries(docs.constants)) {
                    const item = new vscode.CompletionItem(name, vscode.CompletionItemKind.Constant);
                    item.detail = c.signature || name;
                    item.documentation = new vscode.MarkdownString(c.description || '');
                    item.insertText = name;
                    items.push(item);
                }
            }

            // Keywords
            if (docs.keywords) {
                for (const [name, kw] of Object.entries(docs.keywords)) {
                    const item = new vscode.CompletionItem(name, vscode.CompletionItemKind.Keyword);
                    item.detail = `Arena keyword: ${name}`;
                    item.documentation = new vscode.MarkdownString(kw.description || '');
                    item.insertText = name;
                    items.push(item);
                }
            }

            // Types
            if (docs.types) {
                for (const [name, ty] of Object.entries(docs.types)) {
                    const item = new vscode.CompletionItem(name, vscode.CompletionItemKind.TypeParameter);
                    item.detail = `Arena type: ${name}`;
                    item.documentation = new vscode.MarkdownString(ty.description || '');
                    item.insertText = name;
                    items.push(item);
                }
            }

            // Snippets
            if (docs.snippets) {
                for (const snip of docs.snippets) {
                    const item = new vscode.CompletionItem(snip.label, vscode.CompletionItemKind.Snippet);
                    item.detail = snip.detail;
                    item.insertText = new vscode.SnippetString(snip.insertText);
                    item.documentation = new vscode.MarkdownString(snip.documentation || '');
                    items.push(item);
                }
            }

            return items;
        }
    }, '.', '_', 'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z');

    // 3. Signature Help Provider
    const signatureProvider = vscode.languages.registerSignatureHelpProvider('arena', {
        provideSignatureHelp(document, position, token, context) {
            const callContext = getFunctionCallContext(document, position);
            if (!callContext) return null;

            const { functionName, paramIndex } = callContext;
            const fn = docs.functions && docs.functions[functionName];

            const sigHelp = new vscode.SignatureHelp();

            if (fn) {
                const sigInfo = new vscode.SignatureInformation(
                    fn.signature || `${functionName}()`,
                    new vscode.MarkdownString(fn.description || '')
                );

                if (fn.parameters && fn.parameters.length > 0) {
                    sigInfo.parameters = fn.parameters.map(p => {
                        return new vscode.ParameterInformation(
                            p.label || p.name,
                            new vscode.MarkdownString(p.documentation || `Parametre: \`${p.name}\``)
                        );
                    });
                }

                sigHelp.signatures = [sigInfo];
                sigHelp.activeSignature = 0;
                sigHelp.activeParameter = Math.min(
                    paramIndex,
                    (sigInfo.parameters && sigInfo.parameters.length > 0 ? sigInfo.parameters.length - 1 : 0)
                );
                return sigHelp;
            }

            // Fallback for unknown nb_* functions
            if (functionName.startsWith('nb_')) {
                const sigInfo = new vscode.SignatureInformation(
                    `${functionName}(...)`,
                    new vscode.MarkdownString(`**NetModule Router SDK API Fonksiyonu**: \`${functionName}\`\n\n*Parametre detayları için NetModule API kılavuzunu inceleyiniz.*`)
                );
                sigInfo.parameters = [
                    new vscode.ParameterInformation('...', new vscode.MarkdownString('NetModule API parametreleri'))
                ];
                sigHelp.signatures = [sigInfo];
                sigHelp.activeSignature = 0;
                sigHelp.activeParameter = 0;
                return sigHelp;
            }

            return null;
        }
    }, '(', ',');

    context.subscriptions.push(hoverProvider);
    context.subscriptions.push(completionProvider);
    context.subscriptions.push(signatureProvider);
}

function deactivate() {}

module.exports = {
    activate,
    deactivate,
    // Exported for testing
    _loadDocs: loadDocs,
    _getFunctionCallContext: getFunctionCallContext,
    _formatItemHover: formatItemHover,
    _formatFallbackHover: formatFallbackHover
};
