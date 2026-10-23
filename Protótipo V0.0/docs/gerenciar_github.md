# Organizar o repositório pelo VS Code

O notebook (seção 10) prepara a substituição completa da branch `main`: remove os arquivos antigos do repositório e envia uma cópia portátil para `Protótipo V0.0/`. Ele funciona mesmo quando este pacote veio de um ZIP sem histórico Git. Use **Conferir envio** para ver inclusões e exclusões; só depois escolha **Enviar revisão ao GitHub**.

Para trabalhar com arquivos individuais, dê dois cliques em **`Abrir_Gerenciador_GitHub.cmd`** na pasta `BLAZE_prototipo`. Ele abre uma janela própria; não há célula de notebook para executar. Se o Python ainda não foi preparado, execute primeiro `scripts/preparar_notebooks_windows.cmd`.

Também é possível abrir um terminal na pasta `BLAZE_prototipo` no VS Code e executar:

```powershell
python scripts/gerenciar_github.py
```

Instale o Git for Windows e entre na conta GitHub quando o Git solicitar autenticação. Não há necessidade de `git init` ou clone manual.

Na janela:

1. Confira a URL, `main`, a pasta `Protótipo V0.0` e o caminho do pacote. Informe seu nome e e-mail para o registro da revisão.
2. Clique **Carregar GitHub**. A lista esquerda mostra os arquivos locais disponíveis; a direita, os arquivos da branch.
3. Na primeira migração, clique **Preparar substituição completa**. A janela mostra exclusões e novos caminhos. Essa preparação ainda não altera o GitHub.
4. Confira **Prévia das alterações** e clique **Confirmar commit e envio**. O Git envia um commit normal; se outra pessoa alterar a branch no intervalo, o envio será recusado.

Depois, selecione arquivos da esquerda para **Comparar** ou **Preparar envio selecionado**; selecione arquivos da direita para **Baixar**, **Mover** ou **Excluir**. **Criar pasta** acrescenta um `.gitkeep`, porque o GitHub não armazena pastas vazias. Todas as edições remotas aguardam a prévia e a confirmação final. Para descartar mudanças ainda não enviadas, feche e reabra a janela.

O envio completo inclui código, documentação, setups portáteis e modelos. Vídeos, `.bootstrap`, builds, firmware compilado e credenciais locais ficam neste computador. Arquivos locais `config.json`, `secrets.h` e o arquivo de setups históricos não são publicados. A substituição remove cópias antigas desses arquivos que estejam rastreadas no repositório; o histórico de commits permanece disponível.
