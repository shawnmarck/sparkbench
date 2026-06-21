# zsh: spark wrapper so unquoted ? works (nomatch passes literal ?)
# + ? key shows contextual help while typing spark commands
# Installed to /etc/zsh/zshrc.d/spark.zsh by install/20-spark-cli.sh

if [[ -o interactive ]]; then
  setopt nonomatch
fi

spark() {
  command /usr/local/bin/spark "$@"
}

_spark_question_help() {
  if [[ ${LBUFFER} == (#i)spark([[:space:]]*|$) ]]; then
    local -a words
    words=(${=LBUFFER})
    print ""
    command /usr/local/bin/spark "${words[@]:1}" '?'
    return 0
  fi
  zle self-insert
}

if [[ -o interactive ]]; then
  zle -N _spark_question_help
  bindkey -M emacs '?' _spark_question_help
  bindkey -M viins '?' _spark_question_help
fi