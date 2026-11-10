"""Devicon tools shown when browsing; search includes the full catalog."""

# Favor course subjects, general-purpose developer tools, and recognizable
# stacks. List tool names so every installed variant follows the same rule.
COMMON_DEVICONS = frozenset('''
    amazonwebservices anaconda android androidstudio angular angularjs angularmaterial
    ansible antdesign apache apacheairflow apachekafka apachespark apollographql apple
    appwrite archlinux arduino astro awk axios azure azuredevops
    babel bash bazel bitbucket blender bootstrap browserstack bulma bun
    c canva cassandra centos chartjs chrome circleci clion clojure cloudflare
    cmake cobol codepen codex composer cplusplus csharp css css3 cucumber cursor cypressio
    d3js dart datagrip dbeaver debian delphi denojs digitalocean discordjs django
    djangorest docker dot-net dotnetcore drupal duckdb dynamodb
    eclipse elasticsearch electron elixir elm emacs embeddedc entityframeworkcore
    erlang eslint expo express fastapi fastify fedora figma firebase firefox fish
    flask flutter fortran fsharp
    gatsby gcc ghidra gimp git github githubactions githubcodespaces githubcopilot
    gitlab go godot goland googleappscript googlecloud googlecolab gradle grafana
    graphql groovy grpc grunt gulp
    hadoop handlebars haproxy haskell helm heroku hibernate homebrew html5 htmx
    huggingface hugo hyperv
    illustrator influxdb inkscape insomnia intellij ionic istio jasmine java javascript
    jekyll jenkins jest jetbrains jetpackcompose jira jquery json julia junit jupyter jwt
    k3s kaggle kalilinux keras kibana kotlin kubernetes
    laravel latex leetcode less linux linuxmint llvm lodash lua luau
    mariadb markdown materialui matlab matplotlib maven memcached microsoftsqlserver
    mocha mongodb mongoose moodle msbuild mysql
    n8n nano neo4j neovim nestjs netbeans netlify nextjs nginx ngrok nixos nodejs nodemon npm
    nuget numpy nuxt nuxtjs
    oauth objectivec ocaml ohmyzsh ollama openapi opencv opengl opensuse oracle
    p5js pandas perl photoshop php phpstorm playwright plotly pnpm podman poetry
    postcss postgresql postman powershell prisma processing prolog prometheus
    puppeteer pycharm pypi pytest python pytorch
    qt r rabbitmq racket rails railway raspberrypi react reactnative reactrouter
    redhat redis redux replit rider rollup ros rstudio ruby rust rxjs
    safari sass scala scikitlearn seaborn selenium sentry sequelize shadcn slack
    socketio solidity sonarqube spring sqlalchemy sqlite ssh stackoverflow stata
    storybook streamlit supabase svelte swagger swift
    tailwindcss tauri tensorflow terraform tex threejs tmux tomcat toml trello
    typeorm typescript
    ubuntu unity unix unrealengine uv
    vagrant vercel verilog vim visualbasic visualstudio vite vitejs vitest vscode
    vuejs vuetify vulkan wasm webgl webgpu webpack webstorm windows11 wireguard
    woocommerce wordpress xamarin xcode xml yaml yarn zed zig zsh zustand
'''.split())
