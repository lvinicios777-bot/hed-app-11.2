# Grade Horária

App Android para montar a grade horária da escola: turmas de tempo parcial, integral 7h (manhã ou tarde) e integral 9h, com duração da aula, recreios, almoço, limite semanal e PLs por professor, cálculo automático da equipe e geração da grade sem choques.

![ícone](icone-512.png)

## Baixar o APK

Abra a aba **Releases** deste repositório e baixe `GradeHoraria.apk` da versão mais recente. No celular, abra o arquivo e permita a instalação de fontes desconhecidas quando o Android pedir.

Os dados ficam salvos no próprio celular. Para levar a outro aparelho, use **Copiar dados** e **Importar** na etapa 1.

## Como o APK é gerado

A cada envio para a branch `main`, o GitHub Actions (`.github/workflows/apk.yml`) compila o app e publica o APK numa nova Release. Também dá para rodar manualmente em **Actions → Gerar APK → Run workflow**.

## Estrutura

| Caminho | Conteúdo |
|---|---|
| `web/index.html` | O aplicativo inteiro (HTML + JavaScript). Para mudar o app, edite este arquivo. |
| `app/` | Projeto Android que abre a página numa WebView, com cópia para a área de transferência. |
| `app/grade-horaria.keystore` | Chave de assinatura fixa, para que versões novas instalem por cima das antigas. Não serve para publicar na Play Store. |
