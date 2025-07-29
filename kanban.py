import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from ..utils import login_required, log_action, get_shift_name_from_hour, get_shift_boundaries
from sqlalchemy import case, desc
from datetime import datetime
from ..models import db, Veiculo, VeiculoHistorico


kanban_bp = Blueprint('kanban', __name__)

#   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #

# --- Rotas Principais da Aplicação (sem alterações na lógica interna) ---
@kanban_bp.route('/')
@login_required()
def portal():
    return render_template('portal.html')

#   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #

# ROTA DO KANBAN

@kanban_bp.route('/kanban')
@login_required()
def kanban():
    """
    Rota para exibir o Kanban de Veículos com nova ordenação.
    """
    # --- INÍCIO DA CORREÇÃO NA ORDENAÇÃO ---
    # Define a ordem numérica para os status para agrupar os resultados
    status_order = case(
        (Veiculo.status == 'AGUARDANDO', 1),
        (Veiculo.status == 'EM_PROCESSO', 2),
        (Veiculo.status == 'FINALIZADO', 3),
        else_=4
    )

    # Nova query com ordenação simplificada e compatível com SQLite
    veiculos = Veiculo.query.order_by(
        status_order,  # 1. Agrupa por status
        Veiculo.data.asc(), # 2. Ordena por data de criação (mais antigo primeiro) para 'Aguardando'
        Veiculo.hora_inicio.asc(), # 3. Ordena por hora de início para 'Em Processo'
        desc(Veiculo.horario_atualizacao) # 4. Ordena por finalização (mais novo primeiro) para 'Finalizado'
    ).all()
    # --- FIM DA CORREÇÃO NA ORDENAÇÃO ---


    # --- Lógica de Contagem (permanece a mesma) ---
    # ... (o resto da função continua exatamente igual)
    aguardando_count = 0
    em_processo_count = 0
    finalizados_count = 0
    processo_ok = 0
    processo_alerta = 0
    processo_atrasado = 0

    for veiculo in veiculos:
        if veiculo.status == 'AGUARDANDO':
            aguardando_count += 1
        elif veiculo.status == 'FINALIZADO':
            finalizados_count += 1
        elif veiculo.status == 'EM_PROCESSO':
            em_processo_count += 1
            if veiculo.hora_inicio:
                duracao = datetime.now() - veiculo.hora_inicio
                horas_em_processo = duracao.total_seconds() / 3600
                if horas_em_processo < 2:
                    processo_ok += 1
                elif 2 <= horas_em_processo < 4:
                    processo_alerta += 1
                else:
                    processo_atrasado += 1

    kanban_counts = {
        'aguardando': aguardando_count,
        'em_processo': em_processo_count,
        'finalizado': finalizados_count
    }
    processo_contadores = {
        'ok': processo_ok,
        'alerta': processo_alerta,
        'atrasado': processo_atrasado
    }

    for veiculo in veiculos:
        veiculo.hora_inicio_iso = veiculo.hora_inicio.isoformat() if veiculo.hora_inicio else None
        veiculo.finalization_status_class = 'status-ok'
        if veiculo.status == 'FINALIZADO' and veiculo.tempo_descarga:
            try:
                horas_str = veiculo.tempo_descarga.split('h')[0].strip()
                total_hours = float(horas_str)
                if total_hours >= 4:
                    veiculo.finalization_status_class = 'status-atrasado'
                elif total_hours >= 2:
                    veiculo.finalization_status_class = 'status-alerta'
            except (ValueError, IndexError) as e:
                print(f"Erro ao processar tempo de descarga para cor: {e}")

    return render_template('index.html', 
                           veiculos=veiculos, 
                           kanban_counts=kanban_counts, 
                           processo_contadores=processo_contadores)

#   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #

#ROTA PARA ADICIONAR VEICULO

@kanban_bp.route('/adicionar_veiculo', methods=['GET', 'POST'])
@login_required(roles=['ADMIN', 'T1', 'T2', 'T3'])
def adicionar_veiculo():
    if request.method == 'POST':
        form_data = request.form.to_dict()

        # Validação para Tipo de Veículo
        tipo_veiculo_selecionado = form_data.get('tipo_veiculo')
        veiculo_final = ''
        if tipo_veiculo_selecionado == 'Outro':
            veiculo_final = form_data.get('tipo_veiculo_outro', '').strip()
            if not veiculo_final:
                flash('ERRO: Se "Outro" for selecionado para Veículo, você deve especificar o tipo.', 'error')
                return render_template('adicionar_veiculo.html', form_data=form_data)
        elif tipo_veiculo_selecionado in ['Toco', 'Carreta', 'Vuc', 'Truck']:
            veiculo_final = tipo_veiculo_selecionado
        else:
            flash('ERRO: Por favor, selecione um tipo de veículo válido.', 'error')
            return render_template('adicionar_veiculo.html', form_data=form_data)

        # --- NOVA VALIDAÇÃO PARA TIPO DE CARGA ---
        tipo_carga_selecionado = form_data.get('tipo_carga')
        carga_final = ''
        if tipo_carga_selecionado == 'Outra':
            carga_final = form_data.get('tipo_carga_outra', '').strip()
            if not carga_final:
                flash('ERRO: Se "Outra" for selecionado para Carga, você deve especificar o tipo.', 'error')
                return render_template('adicionar_veiculo.html', form_data=form_data)
        elif tipo_carga_selecionado in ['Saca', 'Batida', 'Saca/Batida']:
            carga_final = tipo_carga_selecionado
        else:
            flash('ERRO: Por favor, selecione um tipo de carga válido.', 'error')
            return render_template('adicionar_veiculo.html', form_data=form_data)
        # --- FIM DA VALIDAÇÃO ---

        campos_obrigatorios = ['placa', 'origem', 'turno', 'id_viagem', 'data_planejada', 'data_checkin', 'hora_real_chegada', 'volumetria_sistematica', 'percent_ocupacao', 'rede_contencao', 'doca']
        for campo in campos_obrigatorios:
            if not form_data.get(campo):
                flash(f'ERRO: O campo "{campo.replace("_", " ").title()}" é obrigatório.', 'error')
                return render_template('adicionar_veiculo.html', form_data=form_data)

        placa = form_data.get('placa', '').upper().strip()
        # ... (resto das validações)
        placa_pattern = re.compile(r'^[A-Z]{3}\d[A-Z\d]\d{2}$')
        if not placa_pattern.match(placa.replace('-', '')):
            flash('ERRO: Formato de placa inválido.', 'error')
            return render_template('adicionar_veiculo.html', form_data=form_data)

        # ... (código existente para validação de turno, doca, volumetria, etc.)
        try:
            volumetria = int(form_data.get('volumetria_sistematica'))
            ocupacao = int(form_data.get('percent_ocupacao'))
            if not (0 <= ocupacao <= 100):
                raise ValueError("Percentual de ocupação fora do intervalo.")
        except (ValueError, TypeError):
            flash('ERRO: Volumetria e % de Ocupação devem ser números inteiros (Ocupação de 0-100).', 'error')
            return render_template('adicionar_veiculo.html', form_data=form_data)
            
        doca = form_data.get('doca')
        if doca:
            veiculo_existente = Veiculo.query.filter(Veiculo.doca == doca, Veiculo.status.in_(['AGUARDANDO', 'EM_PROCESSO'])).first()
            if veiculo_existente:
                flash(f'ERRO: A doca {doca} já está ocupada pelo veículo de placa {veiculo_existente.placa}.', 'error')
                return render_template('adicionar_veiculo.html', form_data=form_data)

        try:
            novo_veiculo = Veiculo(
                placa=placa,
                origem=form_data.get('origem'),
                turno=form_data.get('turno'),
                id_viagem=form_data.get('id_viagem'),
                data_planejada=form_data.get('data_planejada'),
                data_checkin=form_data.get('data_checkin'),
                hora_real_chegada=form_data.get('hora_real_chegada'),
                tipo_veiculo=veiculo_final,
                tipo_carga=carga_final,  # USA O VALOR FINAL VALIDADO
                volumetria_sistematica=volumetria,
                percent_ocupacao=ocupacao,
                rede_contencao=form_data.get('rede_contencao'),
                doca=doca,
                observacao=form_data.get('observacao'),
                status='AGUARDANDO'
            )
            db.session.add(novo_veiculo)
            log_action('CRIAR_VEICULO', f"Veículo placa '{placa}' foi adicionado.")
            db.session.commit()
            
            flash(f'Veículo com placa {placa} adicionado com sucesso!', 'veiculo_adicionado')
            return redirect(url_for('kanban.kanban'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ocorreu um erro ao salvar no banco de dados: {e}', 'error')
            return render_template('adicionar_veiculo.html', form_data=form_data)

    return render_template('adicionar_veiculo.html', form_data={})

#   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #

#editar veiculo
@kanban_bp.route('/editar_veiculo/<int:veiculo_id>', methods=['GET', 'POST'])
@login_required(roles=['ADMIN', 'T1', 'T2', 'T3'])
def editar_veiculo(veiculo_id):
    veiculo = Veiculo.query.get_or_404(veiculo_id)
    if veiculo.status == 'FINALIZADO' and session.get('role') != 'ADMIN':
        flash('Você não tem permissão para editar um veículo finalizado.', 'danger')
        return redirect(url_for('kanban.kanban'))
    if request.method == 'POST':
        # Validação para Tipo de Veículo
        tipo_veiculo_selecionado = request.form.get('tipo_veiculo')
        veiculo_final = ''
        if tipo_veiculo_selecionado == 'Outro':
            veiculo_final = request.form.get('tipo_veiculo_outro', '').strip()
            if not veiculo_final:
                flash('ERRO: Se "Outro" for selecionado para Veículo, você deve especificar o tipo.', 'error')
                return render_template('editar_veiculo.html', veiculo=veiculo)
        elif tipo_veiculo_selecionado in ['Toco', 'Carreta', 'Vuc', 'Truck']:
            veiculo_final = tipo_veiculo_selecionado
        else:
            flash('ERRO: Por favor, selecione um tipo de veículo válido.', 'error')
            return render_template('editar_veiculo.html', veiculo=veiculo)

        # --- NOVA VALIDAÇÃO PARA TIPO DE CARGA ---
        tipo_carga_selecionado = request.form.get('tipo_carga')
        carga_final = ''
        if tipo_carga_selecionado == 'Outra':
            carga_final = request.form.get('tipo_carga_outra', '').strip()
            if not carga_final:
                flash('ERRO: Se "Outra" for selecionado para Carga, você deve especificar o tipo.', 'error')
                return render_template('editar_veiculo.html', veiculo=veiculo)
        elif tipo_carga_selecionado in ['Saca', 'Batida', 'Saca/Batida']:
            carga_final = tipo_carga_selecionado
        else:
            flash('ERRO: Por favor, selecione um tipo de carga válido.', 'error')
            return render_template('editar_veiculo.html', veiculo=veiculo)
        # --- FIM DA VALIDAÇÃO ---
        
        placa = request.form.get('placa', '').upper().strip()
        # ... (resto das validações)
        placa_pattern = re.compile(r'^[A-Z]{3}\d[A-Z\d]\d{2}$')
        if not placa_pattern.match(placa.replace('-', '')):
            flash('ERRO: Formato de placa inválido.', 'error')
            return render_template('editar_veiculo.html', veiculo=veiculo)

        doca = request.form.get('doca')
        if doca:
            veiculo_existente = Veiculo.query.filter(Veiculo.doca == doca, Veiculo.status.in_(['AGUARDANDO', 'EM_PROCESSO']), Veiculo.id != veiculo_id).first()
            if veiculo_existente:
                flash(f'ERRO: A doca {doca} já está ocupada pelo veículo de placa {veiculo_existente.placa}.', 'error')
                return render_template('editar_veiculo.html', veiculo=veiculo)
        try:
            veiculo.placa = placa
            veiculo.origem = request.form.get('origem')
            veiculo.doca = doca
            veiculo.turno = request.form.get('turno')
            veiculo.data_planejada = request.form.get('data_planejada')
            veiculo.data_checkin = request.form.get('data_checkin')
            veiculo.hora_real_chegada = request.form.get('hora_real_chegada')
            veiculo.id_viagem = request.form.get('id_viagem')
            veiculo.tipo_veiculo = veiculo_final
            veiculo.tipo_carga = carga_final # USA O VALOR FINAL VALIDADO
            veiculo.rede_contencao = request.form.get('rede_contencao')
            veiculo.observacao = request.form.get('observacao')
            log_action('EDITAR_VEICULO', f"Veículo placa '{placa}' foi editado.") 
            db.session.commit()
            flash(f'Veículo {placa} atualizado com sucesso!', 'success')
            return redirect(url_for('kanban.kanban'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar o veículo: {e}', 'error')
            return render_template('editar_veiculo.html', veiculo=veiculo)
    return render_template('editar_veiculo.html', veiculo=veiculo)

#   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #

#excluir veiculo
@kanban_bp.route('/excluir_veiculo/<int:veiculo_id>', methods=['POST'])
@login_required(roles=['ADMIN', 'T1', 'T2', 'T3'])
def excluir_veiculo(veiculo_id):
    veiculo = Veiculo.query.get_or_404(veiculo_id)
    if veiculo.status == 'AGUARDANDO':
        try:
            db.session.delete(veiculo)
            log_action('EXCLUIR_VEICULO', f"Veículo placa '{veiculo.placa}' foi excluído.")
            db.session.commit()
            flash(f'Veículo de placa {veiculo.placa} excluído com sucesso.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao excluir o veículo: {e}', 'error')
    else:
        flash('Apenas veículos no status "Aguardando" podem ser excluídos.', 'warning')
    return redirect(url_for('kanban.kanban'))

#   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #


#ATUALIZAR_STATUS
@kanban_bp.route('/atualizar_status', methods=['POST'])
@login_required(roles=['ADMIN', 'T1', 'T2', 'T3'])
def atualizar_status():
    data = request.get_json()
    veiculo = db.session.get(Veiculo, data['veiculo_id'])
    if not veiculo:
        return jsonify({'success': False, 'message': 'Veículo não encontrado'}), 404

    current_status = veiculo.status
    novo_status = data['novo_status'].replace('column-', '')

    # Lógica de transição
    if current_status == 'AGUARDANDO' and novo_status == 'EM_PROCESSO':
        veiculo.hora_inicio = datetime.now()
        veiculo.status = 'EM_PROCESSO'
    elif current_status == 'EM_PROCESSO' and novo_status == 'FINALIZADO':
        veiculo.horario_atualizacao = datetime.now()
        veiculo.status = 'FINALIZADO'
        veiculo.turno_finalizacao = get_shift_name_from_hour(veiculo.horario_atualizacao.hour)
        if veiculo.hora_inicio:
            duracao = veiculo.horario_atualizacao - veiculo.hora_inicio
            total_seconds = duracao.total_seconds()
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)
            if hours == 0 and minutes == 0 and total_seconds > 0: minutes = 1
            veiculo.tempo_descarga = f"{hours}h {minutes}m"
    elif current_status == 'FINALIZADO' and novo_status == 'EM_PROCESSO':
        veiculo.status = 'EM_PROCESSO'
        veiculo.horario_atualizacao = None
        veiculo.tempo_descarga = None
        veiculo.turno_finalizacao = None
    else:
        return jsonify({'success': False, 'message': 'Transição de status inválida'}), 400
    
    log_action('ATUALIZAR_STATUS', f"Status do veículo '{veiculo.placa}' alterado de '{current_status}' para '{novo_status}'.") # ADICIONE AQUI

    db.session.commit()
    
    # Lógica para definir a classe de cor (status) do card finalizado
    finalization_class = 'status-ok'
    if veiculo.status == 'FINALIZADO' and veiculo.tempo_descarga:
        try:
            horas_str = veiculo.tempo_descarga.split('h')[0].strip()
            total_hours = float(horas_str)
            if total_hours >= 4: finalization_class = 'status-atrasado'
            elif total_hours >= 2: finalization_class = 'status-alerta'
        except (ValueError, IndexError): pass

    # Serializa os dados do veículo em um dicionário para enviar como JSON
    veiculo_data = {
        'id': veiculo.id,
        'placa': veiculo.placa,
        'origem': veiculo.origem,
        'id_viagem': veiculo.id_viagem,
        'doca': veiculo.doca,
        'turno': veiculo.turno,
        'tipo_veiculo': veiculo.tipo_veiculo,
        'tipo_carga': veiculo.tipo_carga,
        'status': veiculo.status,
        'hora_inicio': veiculo.hora_inicio.isoformat() if veiculo.hora_inicio else None,
        'horario_atualizacao': veiculo.horario_atualizacao.isoformat() if veiculo.horario_atualizacao else None,
        'turno_finalizacao': veiculo.turno_finalizacao,
        'tempo_descarga': veiculo.tempo_descarga,
        'finalization_status_class': finalization_class
    }

    return jsonify({'success': True, 'veiculo': veiculo_data})


#   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #

#arquivar_manualmente
@kanban_bp.route('/arquivar_manualmente', methods=['POST'])
@login_required()
def arquivar_manualmente():
    # Pega o turno atual
    turno_atual = get_shift_name_from_hour(datetime.now().hour)
    
    # Busca todos os veículos com status FINALIZADO
    veiculos_finalizados = Veiculo.query.filter_by(status='FINALIZADO').all()
    
    # Filtra para arquivar apenas os de turnos anteriores
    veiculos_a_arquivar = [
        v for v in veiculos_finalizados if v.turno_finalizacao != turno_atual
    ]

    if not veiculos_a_arquivar:
        flash('Nenhum veículo de turnos anteriores para arquivar.', 'warning')
        return redirect(url_for('kanban.kanban'))

    try:
        for veiculo in veiculos_a_arquivar:
            historico_entry = VeiculoHistorico(
                placa=veiculo.placa, origem=veiculo.origem, turno=veiculo.turno, data=veiculo.data,
                data_planejada=veiculo.data_planejada, data_checkin=veiculo.data_checkin,
                hora_real_chegada=veiculo.hora_real_chegada, id_viagem=veiculo.id_viagem,
                hora_inicio=veiculo.hora_inicio, volumetria_sistematica=veiculo.volumetria_sistematica,
                tempo_descarga=veiculo.tempo_descarga, percent_ocupacao=veiculo.percent_ocupacao,
                status_final='FINALIZADO', doca=veiculo.doca, tipo_carga=veiculo.tipo_carga,
                tipo_veiculo=veiculo.tipo_veiculo, rede_contencao=veiculo.rede_contencao,
                horario_atualizacao=veiculo.horario_atualizacao, turno_finalizacao=veiculo.turno_finalizacao,
                observacao=veiculo.observacao, data_arquivamento=datetime.now()
            )
            db.session.add(historico_entry)
            db.session.delete(veiculo)
        
        db.session.commit()
        flash(f'{len(veiculos_a_arquivar)} veículo(s) de turnos anteriores foram arquivados.', 'success')
    
    except Exception as e:
        db.session.rollback()
        flash(f'Ocorreu um erro ao arquivar: {e}', 'error')
    log_action('ARQUIVAR_VEICULOS', f"{len(veiculos_a_arquivar)} veículos foram arquivados manualmente.")
    return redirect(url_for('kanban.kanban'))

#   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #


@kanban_bp.route('/api/veiculo/<int:veiculo_id>')
@login_required()
def get_veiculo_details(veiculo_id):
    # Busca o veículo no banco de dados. Se não encontrar, retorna erro 404.
    veiculo = Veiculo.query.get_or_404(veiculo_id)
    
    # Cria um dicionário com todos os dados que queremos mostrar
    details = {
        'placa': veiculo.placa,
        'origem': veiculo.origem,
        'turno': veiculo.turno,
        'id_viagem': veiculo.id_viagem,
        'data_planejada': veiculo.data_planejada,
        'data_checkin': veiculo.data_checkin,
        'hora_real_chegada': veiculo.hora_real_chegada,
        'tipo_veiculo': veiculo.tipo_veiculo,
        'tipo_carga': veiculo.tipo_carga,
        'volumetria_sistematica': veiculo.volumetria_sistematica,
        'percent_ocupacao': f"{veiculo.percent_ocupacao}%" if veiculo.percent_ocupacao is not None else 'N/A',
        'rede_contencao': veiculo.rede_contencao,
        'doca': veiculo.doca,
        'observacao': veiculo.observacao,
        # Adiciona também informações de status, se relevante
        'status': veiculo.status,
        'hora_inicio': veiculo.hora_inicio.strftime('%d/%m/%Y %H:%M:%S') if veiculo.hora_inicio else 'N/A',
        'horario_atualizacao': veiculo.horario_atualizacao.strftime('%d/%m/%Y %H:%M:%S') if veiculo.horario_atualizacao else 'N/A',
        'tempo_descarga': veiculo.tempo_descarga
    }
    
    # Retorna os dados como JSON
    return jsonify(details)

#   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #

#Status da doca
@kanban_bp.route('/api/dock_status')
@login_required()
def api_dock_status():
    lista_docas = list(range(1, 31)) + list(range(61, 91))
    dock_data = {str(i): {'status': 'LIVRE', 'placa': None, 'timing_status': None, 'hora_inicio': None, 'veiculo_id': None} for i in lista_docas}
    
    veiculos_em_docas = Veiculo.query.filter(Veiculo.doca.isnot(None), Veiculo.status.in_(['AGUARDANDO', 'EM_PROCESSO'])).all()
    
    for veiculo in veiculos_em_docas:
        cleaned_dock_str = str(veiculo.doca).strip() 
        
        if cleaned_dock_str in dock_data:
            timing_status = None
            hora_inicio_iso = None # Inicializa a variável
            
            # --- INÍCIO DA CORREÇÃO ---
            # Define o tempo de início para veículos EM PROCESSO
            if veiculo.status == 'EM_PROCESSO' and veiculo.hora_inicio:
                try:
                    duration = datetime.now() - veiculo.hora_inicio
                    hora_inicio_iso = veiculo.hora_inicio.isoformat()
                    if duration.total_seconds() > 14400: # 4 horas
                        timing_status = 'LATE' 
                    elif duration.total_seconds() > 7200: # 2 horas
                        timing_status = 'WARNING'
                    else:
                        timing_status = 'ON_TIME'
                except TypeError:
                    timing_status = None
            
            # ADICIONADO: Define o tempo de início para veículos AGUARDANDO (usa a data de criação)
            elif veiculo.status == 'AGUARDANDO' and veiculo.data:
                hora_inicio_iso = veiculo.data.isoformat()
            # --- FIM DA CORREÇÃO ---

            dock_data[cleaned_dock_str] = {
                'status': veiculo.status.upper(), 
                'placa': veiculo.placa,
                'timing_status': timing_status,
                'hora_inicio': hora_inicio_iso, # Agora envia o tempo de início para ambos os status
                'veiculo_id': veiculo.id 
            }
    
    return jsonify(dock_data)

#   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #   #


@kanban_bp.route('/api/status_counts')
@login_required()
def get_status_counts():
    now = datetime.now()
    current_shift_name = get_shift_name_from_hour(now.hour) # Pega o turno baseado na hora atual
    
    start_shift, end_shift = get_shift_boundaries(now, current_shift_name) # Calcula os limites corretos para 'now' e 'current_shift_name'

    # --- ADICIONE ESTES PRINTS PARA DEPURAR OS LIMITES DE TEMPO E AS CONTAGENS ---
    print(f"\n--- API STATUS COUNTS DEBUG ---")
    print(f"Hora Atual da Requisição: {now}")
    print(f"Turno Atual Detectado: {current_shift_name}")
    print(f"Limites do Turno: {start_shift} (Início) a {end_shift} (Fim)")
    
    # Contar FINALIZADOS da tabela principal (ainda não arquivados)
    finished_in_current_table = Veiculo.query.filter(
        Veiculo.status == 'FINALIZADO',
        Veiculo.horario_atualizacao >= start_shift,
        Veiculo.horario_atualizacao < end_shift
    ).count()

    # Contar FINALIZADOS da tabela de histórico (já arquivados)
    finished_in_history_table = 0
    if start_shift and end_shift: # Garante que os limites são válidos antes de consultar o histórico
        finished_in_history_table = VeiculoHistorico.query.filter(
            VeiculoHistorico.horario_atualizacao >= start_shift,
            VeiculoHistorico.horario_atualizacao < end_shift
        ).count()
    
    # Soma os finalizados das duas tabelas para o turno atual
    finished_in_shift_count = Veiculo.query.filter_by(status='FINALIZADO').count()

    waiting_vehicles_count = Veiculo.query.filter_by(status='AGUARDANDO').count()
    in_process_vehicles_count = Veiculo.query.filter_by(status='EM_PROCESSO').count()
    
    print(f"Contagens atualizadas -> Finalizados: {finished_in_shift_count}, Aguardando: {waiting_vehicles_count}, Em Processo: {in_process_vehicles_count}")

    return jsonify({
        'shift_name': current_shift_name,
        'finished_count': finished_in_shift_count,
        'waiting_count': waiting_vehicles_count,
        'in_process_count': in_process_vehicles_count
    })

# Em app.py, adicione estas duas funções


# --- Rotas e Funções de Tema (sem alterações) ---
@kanban_bp.route('/set-theme/<theme>')
def set_theme(theme):
    session['theme'] = theme
    return jsonify(success=True)

@kanban_bp.route('/vehicles')
@login_required(roles=['ADMIN', 'T1', 'T2', 'T3', 'AUDITOR'])
def list_vehicles():
    """
    Lista todos os veículos ativos e históricos com filtros.
    Agora, o filtro de data padrão é o turno atual.
    """
    # ... (código existente para pegar filtros da requisição, se houver)
    data_inicio_str = request.args.get('data_inicio')
    data_fim_str = request.args.get('data_fim')
    placa_filtro = request.args.get('placa')
    status_filtro = request.args.get('status')
    motorista_filtro = request.args.get('motorista')
    tipo_veiculo_filtro = request.args.get('tipo_veiculo')
    turno_filtro = request.args.get('turno') # Novo filtro para turno

    # Calcular o turno atual como padrão se nenhum filtro de data for fornecido
    default_data_inicio_str = ''
    default_data_fim_str = ''
    if not data_inicio_str and not data_fim_str:
        now = datetime.now()
        current_shift_name = get_shift_name_from_hour(now.hour)
        start_shift, end_shift = get_shift_boundaries(now, current_shift_name)
        default_data_inicio_str = start_shift.strftime('%d/%m/%Y %H:%M:%S') if start_shift else ''
        default_data_fim_str = end_shift.strftime('%d/%m/%Y %H:%M:%S') if end_shift else ''
        
        # Usar os defaults para a query se não houver filtros explícitos
        data_inicio_str = default_data_inicio_str
        data_fim_str = default_data_fim_str

    data_inicio = None
    if data_inicio_str:
        try:
            data_inicio = datetime.strptime(data_inicio_str, '%d/%m/%Y %H:%M:%S')
        except ValueError:
            flash("Formato de data de início inválido. Ignorando filtro.", "warning")
            data_inicio = None # Resetar para não usar data inválida

    data_fim = None
    if data_fim_str:
        try:
            data_fim = datetime.strptime(data_fim_str, '%d/%m/%Y %H:%M:%S')
        except ValueError:
            flash("Formato de data final inválido. Ignorando filtro.", "warning")
            data_fim = None # Resetar para não usar data inválida


    # Construir a query base para veículos ativos
    query_ativos = Veiculo.query
    query_historico = VeiculoHistorico.query

    # Aplicar filtros de data (se definidos, seja por padrão ou pelo usuário)
    if data_inicio:
        query_ativos = query_ativos.filter(Veiculo.data >= data_inicio)
        query_historico = query_historico.filter(VeiculoHistorico.data >= data_inicio)
    if data_fim:
        query_ativos = query_ativos.filter(Veiculo.data <= data_fim)
        query_historico = query_historico.filter(VeiculoHistorico.data <= data_fim)

    # ... (restante da aplicação de filtros de placa, status, motorista, tipo_veiculo, etc.)
    if placa_filtro:
        query_ativos = query_ativos.filter(Veiculo.placa.ilike(f'%{placa_filtro}%'))
        query_historico = query_historico.filter(VeiculoHistorico.placa.ilike(f'%{placa_filtro}%'))
    if status_filtro and status_filtro != 'todos':
        query_ativos = query_ativos.filter(Veiculo.status == status_filtro)
        query_historico = query_historico.filter(VeiculoHistorico.status_final == status_filtro)
    if motorista_filtro:
        query_ativos = query_ativos.filter(Veiculo.motorista.ilike(f'%{motorista_filtro}%'))
        query_historico = query_historico.filter(VeiculoHistorico.motorista.ilike(f'%{motorista_filtro}%'))
    if tipo_veiculo_filtro and tipo_veiculo_filtro != 'todos':
        query_ativos = query_ativos.filter(Veiculo.tipo_veiculo == tipo_veiculo_filtro)
        query_historico = query_historico.filter(VeiculoHistorico.tipo_veiculo == tipo_veiculo_filtro)
    
    # Aplicar filtro de turno, se houver (para veículos ativos e históricos)
    if turno_filtro and turno_filtro != 'todos':
        query_ativos = query_ativos.filter(Veiculo.turno == turno_filtro)
        query_historico = query_historico.filter(VeiculoHistorico.turno == turno_filtro)


    veiculos = query_ativos.order_by(Veiculo.data.desc()).all()
    historico = query_historico.order_by(VeiculoHistorico.data.desc()).all()

    # Combinar e ordenar os resultados
    todos_veiculos = sorted(veiculos + historico, key=lambda x: x.data, reverse=True)

    # ... (restante do código para renderizar o template)
    return render_template(
        'list_vehicles.html', # Ou o nome do seu template de listagem
        veiculos=todos_veiculos,
        placa_filtro=placa_filtro,
        status_filtro=status_filtro,
        motorista_filtro=motorista_filtro,
        tipo_veiculo_filtro=tipo_veiculo_filtro,
        turno_filtro=turno_filtro, # Passa o filtro de turno para o template
        default_data_inicio=default_data_inicio_str, # Passa as datas padrão
        default_data_fim=default_data_fim_str,       # Passa as datas padrão
        # ... outras variáveis que você já passa
    )
